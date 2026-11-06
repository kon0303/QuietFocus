"""Main window and application orchestration."""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import messagebox
from typing import Callable

from ..audio import AppSnapshot, AudioController, EngineSnapshot
from ..config import MAX_INTERVAL, MIN_INTERVAL, Settings
from ..paths import APP_TITLE, data_dir, resource_path
from ..tray import TrayManager
from ..winutil import (
    apply_modern_titlebar,
    get_autostart_command,
    is_autostart_enabled,
    open_data_folder,
    set_autostart,
    wait_for_show_event,
)
from . import theme
from .icons import IconProvider
from .theme import FONT_CANDIDATES
from .widgets import (
    AppRow,
    EmptyState,
    HoverButton,
    ScrollableFrame,
    Slider,
    ToggleSwitch,
    px,
)

log = logging.getLogger(__name__)


class QuietFocusApp:
    def __init__(
        self, *, start_minimized: bool = False, show_event: int | None = None
    ) -> None:
        self.settings = Settings()
        self._show_event = show_event
        self._start_hidden = bool(start_minimized or self.settings.start_minimized)
        self._closing = False
        self._snapshot: EngineSnapshot | None = None
        self._rows: dict[str, AppRow] = {}
        self._row_order: list[str] = []
        self._snapshot_queue: queue.Queue[EngineSnapshot] = queue.Queue(maxsize=2)
        self._commands: queue.Queue[Callable[[], None]] = queue.Queue()
        self._settings_window: tk.Toplevel | None = None
        self._autostart_switch: ToggleSwitch | None = None
        self._poll_id: str | None = None
        self._auto_select_pending = self.settings.is_new
        self._auto_select_deadline = time.monotonic() + 90
        self._banner_visible = False
        self._tray_state: tuple | None = None
        self._last_interval_apply: str | None = None
        self._interval_slider: Slider | None = None

        self.root = tk.Tk()
        self.root.withdraw()
        self.scale = self._detect_scale()
        self.family = self._pick_font()
        self.fonts = self._make_fonts()
        self._setup_root()
        self._build_ui()
        self._setup_tray()
        self._engine = AudioController(
            get_selected=self.settings.selected_keys,
            get_enabled=lambda: self.settings.enabled,
            get_interval=lambda: self.settings.poll_interval,
            on_snapshot=self._enqueue_snapshot,
            get_restore_on_exit=lambda: self.settings.restore_on_exit,
        )
        self._engine.start()
        if self._show_event:
            threading.Thread(
                target=self._wait_for_show_request,
                name="QuietFocusShowEvent",
                daemon=True,
            ).start()
        self._poll_id = self.root.after(80, self._poll)
        self.root.after(180, self._show_initial_window)
        self.root.after(900, lambda: apply_modern_titlebar(self.root.winfo_id()))

    def _wait_for_show_request(self) -> None:
        while not self._closing:
            if wait_for_show_event(self._show_event, 500):
                if self._closing:
                    return
                log.info("Show request from a second instance")
                self._commands.put(self.show_window)

    # ------------------------------------------------------------------ setup
    def _detect_scale(self) -> float:
        try:
            raw = self.root.winfo_fpixels("1i") / 96.0
        except Exception:
            raw = 1.0
        return max(0.9, min(1.7, raw))

    def _pick_font(self) -> str:
        try:
            families = {name.casefold(): name for name in tkfont.families(self.root)}
        except Exception:
            families = {}
        for candidate in FONT_CANDIDATES:
            if candidate.casefold() in families:
                return families[candidate.casefold()]
        return "Segoe UI"

    def _make_fonts(self) -> dict[str, tuple]:
        family = self.family
        return {
            "title": (family, 21, "bold"),
            "brand": (family, 9, "bold"),
            "subtitle": (family, 9),
            "section": (family, 12, "bold"),
            "body": (family, 9),
            "small": (family, 8),
            "button": (family, 9, "bold"),
            "app_name": (family, 10, "bold"),
            "detail": (family, 8),
            "chip": (family, 8, "bold"),
            "sound": (family, 9, "bold"),
            "empty_title": (family, 12, "bold"),
            "count": (family, 9, "bold"),
            "master": (family, 10, "bold"),
            "setting_title": (family, 10, "bold"),
            "setting_desc": (family, 8),
            "dialog_title": (family, 16, "bold"),
        }

    def _setup_root(self) -> None:
        self.root.title(APP_TITLE)
        self.root.configure(bg=theme.BG)
        try:
            self.root.iconbitmap(resource_path("assets", "icon.ico"))
        except Exception:
            pass
        width = px(1000, self.scale)
        height = px(706, self.scale)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(width, int(screen_w * 0.88))
        height = min(height, int(screen_h * 0.90))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.minsize(min(px(840, self.scale), screen_w), min(px(570, self.scale), screen_h))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.report_callback_exception = self._report_callback_exception
        self.root.bind("<Escape>", lambda _e: self._close_settings())
        self.root.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        log.info(
            "Tk ready: scale=%.2f screen=%sx%s geometry=%s",
            self.scale,
            screen_w,
            screen_h,
            self.root.winfo_geometry(),
        )

    def _on_mousewheel(self, event) -> None:
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, KeyError):
            return
        canvas = getattr(getattr(self, "scroll", None), "canvas", None)
        while widget is not None and canvas is not None:
            if widget is canvas:
                delta = -2 if event.delta > 0 else 2
                self.scroll.scroll(delta)
                return
            widget = getattr(widget, "master", None)

    def _report_callback_exception(self, exc_type, exc_value, exc_tb) -> None:
        log.exception("Unhandled UI exception", exc_info=(exc_type, exc_value, exc_tb))
        try:
            messagebox.showerror(APP_TITLE, f"界面出现了一个错误：\n{exc_value}", parent=self.root)
        except Exception:
            pass

    # --------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.icons = IconProvider(self.root, self.scale)
        self.logo_image = self.icons.logo(size=px(47, self.scale))

        self._build_header()
        body = tk.Frame(self.root, bg=theme.BG)
        body.pack(fill="both", expand=True, padx=px(26, self.scale), pady=(px(14, self.scale), 0))
        self._body = body

        self._build_toolbar(body)
        self.banner = self._make_banner(body)
        self.card = self._make_card(body)
        self._build_footer(body)
        self._build_statusbar()

        self.empty = EmptyState(
            self.scroll.inner,
            self.fonts,
            self.refresh,
            scale=self.scale,
        )
        self.empty.grid(row=0, column=0, sticky="nsew")
        self.empty.set_loading(True)

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=theme.CARD)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=theme.CARD)
        inner.pack(fill="x", padx=px(28, self.scale), pady=(px(17, self.scale), px(16, self.scale)))

        logo = tk.Label(inner, image=self.logo_image, bg=theme.CARD, bd=0)
        logo.pack(side="left", padx=(0, px(13, self.scale)))

        title_block = tk.Frame(inner, bg=theme.CARD)
        title_block.pack(side="left", fill="y")
        title_line = tk.Frame(title_block, bg=theme.CARD)
        title_line.pack(anchor="w")
        tk.Label(
            title_line,
            text="静界",
            bg=theme.CARD,
            fg=theme.TEXT,
            font=self.fonts["title"],
        ).pack(side="left")
        tk.Label(
            title_line,
            text="QuietFocus",
            bg=theme.CARD,
            fg=theme.ACCENT_DARK,
            font=self.fonts["brand"],
            padx=px(8, self.scale),
            pady=px(3, self.scale),
        ).pack(side="left", padx=(px(8, self.scale), 0), pady=(px(6, self.scale), 0))
        tk.Label(
            title_block,
            text="后台应用自动静音 · 回到前台自动恢复",
            bg=theme.CARD,
            fg=theme.SUBTEXT,
            font=self.fonts["subtitle"],
        ).pack(anchor="w", pady=(px(2, self.scale), 0))

        master = tk.Frame(inner, bg=theme.CARD)
        master.pack(side="right", anchor="center")
        text = tk.Frame(master, bg=theme.CARD)
        text.pack(side="left", padx=(0, px(11, self.scale)))
        tk.Label(
            text,
            text="自动静音",
            bg=theme.CARD,
            fg=theme.TEXT,
            font=self.fonts["master"],
        ).pack(anchor="e")
        self.master_status = tk.Label(
            text,
            text="已开启",
            bg=theme.CARD,
            fg=theme.ACCENT_DARK,
            font=self.fonts["small"],
        )
        self.master_status.pack(anchor="e", pady=(px(1, self.scale), 0))
        self.master_switch = ToggleSwitch(
            master,
            self.settings.enabled,
            self._toggle_enabled,
            scale=self.scale,
            bg=theme.CARD,
        )
        self.master_switch.pack(side="left")
        self._update_master_label()

        tk.Frame(self.root, bg=theme.BORDER, height=1).pack(fill="x")

    def _build_toolbar(self, parent) -> None:
        toolbar = tk.Frame(parent, bg=theme.BG)
        toolbar.pack(fill="x")
        left = tk.Frame(toolbar, bg=theme.BG)
        left.pack(side="left")
        tk.Label(
            left,
            text="音频应用",
            bg=theme.BG,
            fg=theme.TEXT,
            font=self.fonts["section"],
        ).pack(side="left", anchor="center")
        self.count_chip = tk.Label(
            left,
            text="扫描中",
            bg=theme.ACCENT_SOFT,
            fg=theme.ACCENT_DARK,
            font=self.fonts["count"],
            padx=px(8, self.scale),
            pady=px(2, self.scale),
        )
        self.count_chip.pack(side="left", padx=(px(9, self.scale), 0), pady=(px(2, self.scale), 0))
        self.summary_label = tk.Label(
            left,
            text="",
            bg=theme.BG,
            fg=theme.SUBTEXT,
            font=self.fonts["small"],
        )
        self.summary_label.pack(side="left", padx=(px(12, self.scale), 0), anchor="center")

        right = tk.Frame(toolbar, bg=theme.BG)
        right.pack(side="right")
        self.refresh_button = HoverButton(
            right,
            "刷新",
            self.refresh,
            bg=theme.BG,
            hover_bg=theme.CARD,
            fg=theme.SUBTEXT,
            hover_fg=theme.TEXT,
            font=self.fonts["button"],
            padx=px(10, self.scale),
            pady=px(5, self.scale),
        )
        self.refresh_button.pack(side="right")
        self.clear_button = HoverButton(
            right,
            "全部取消",
            self.clear_all,
            bg=theme.BG,
            hover_bg=theme.CARD,
            fg=theme.SUBTEXT,
            hover_fg=theme.TEXT,
            font=self.fonts["button"],
            padx=px(10, self.scale),
            pady=px(5, self.scale),
        )
        self.clear_button.pack(side="right", padx=(0, px(2, self.scale)))
        self.select_all_button = HoverButton(
            right,
            "全部勾选",
            self.select_all,
            bg=theme.BG,
            hover_bg=theme.ACCENT_SOFT,
            fg=theme.ACCENT_DARK,
            hover_fg=theme.ACCENT_DARK,
            font=self.fonts["button"],
            padx=px(10, self.scale),
            pady=px(5, self.scale),
        )
        self.select_all_button.pack(side="right", padx=(0, px(2, self.scale)))

    def _make_banner(self, parent) -> tk.Frame:
        banner = tk.Frame(
            parent,
            bg=theme.ACCENT_SOFT,
            highlightbackground=theme.ACCENT_SOFT_2,
            highlightthickness=1,
        )
        inner = tk.Frame(banner, bg=theme.ACCENT_SOFT)
        inner.pack(fill="x", padx=px(14, self.scale), pady=px(9, self.scale))
        self.banner_text = tk.Label(
            inner,
            text="",
            bg=theme.ACCENT_SOFT,
            fg=theme.ACCENT_DARK,
            font=self.fonts["body"],
            anchor="w",
            justify="left",
        )
        self.banner_text.pack(side="left", fill="x", expand=True)
        HoverButton(
            inner,
            "知道了",
            self._hide_banner,
            bg=theme.ACCENT_SOFT,
            hover_bg=theme.ACCENT_SOFT_2,
            fg=theme.ACCENT_DARK,
            font=self.fonts["small"],
            padx=px(9, self.scale),
            pady=px(3, self.scale),
        ).pack(side="right", padx=(px(10, self.scale), 0))
        return banner

    def _make_card(self, parent) -> tk.Frame:
        card = tk.Frame(
            parent,
            bg=theme.CARD,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        card.pack(fill="both", expand=True, pady=(px(9, self.scale), 0))

        header = tk.Frame(card, bg=theme.CARD_HEADER)
        header.pack(fill="x")
        header.grid_columnconfigure(0, minsize=px(49, self.scale))
        header.grid_columnconfigure(1, minsize=px(42, self.scale))
        header.grid_columnconfigure(2, weight=1)
        header.grid_columnconfigure(3, minsize=px(74, self.scale))
        header.grid_columnconfigure(4, minsize=px(70, self.scale))
        for column, text, anchor in (
            (0, "控制", "center"),
            (2, "应用", "w"),
            (3, "状态", "center"),
            (4, "声音", "center"),
        ):
            label = tk.Label(
                header,
                text=text,
                bg=theme.CARD_HEADER,
                fg=theme.FAINT,
                font=self.fonts["small"],
                anchor=anchor,
            )
            if column == 2:
                label.grid(row=0, column=column, sticky="w", pady=px(8, self.scale))
            elif column == 3:
                label.grid(row=0, column=column, sticky="e", padx=(0, px(15, self.scale)), pady=px(8, self.scale))
            elif column == 4:
                label.grid(row=0, column=column, sticky="e", padx=(0, px(27, self.scale)), pady=px(8, self.scale))
            else:
                label.grid(row=0, column=column, pady=px(8, self.scale))
        tk.Frame(card, bg=theme.BORDER, height=1).pack(fill="x")

        self.scroll = ScrollableFrame(card, bg=theme.CARD)
        self.scroll.pack(fill="both", expand=True)
        return card

    def _build_footer(self, parent) -> None:
        footer = tk.Frame(parent, bg=theme.BG)
        footer.pack(fill="x", pady=(px(8, self.scale), px(2, self.scale)))
        tk.Label(
            footer,
            text="勾选应用后，切到后台自动静音；回到前台恢复声音。",
            bg=theme.BG,
            fg=theme.FAINT,
            font=self.fonts["small"],
        ).pack(side="left")
        self.remembered_button = HoverButton(
            footer,
            "",
            self._manage_missing,
            bg=theme.BG,
            hover_bg=theme.CARD,
            fg=theme.ACCENT_DARK,
            font=self.fonts["small"],
            padx=px(6, self.scale),
            pady=px(2, self.scale),
        )
        self.remembered_label = tk.Label(
            footer,
            text="设置已保存在本机",
            bg=theme.BG,
            fg=theme.FAINT,
            font=self.fonts["small"],
        )
        self.remembered_label.pack(side="right")

    def _build_statusbar(self) -> None:
        status = tk.Frame(self.root, bg=theme.BG)
        status.pack(fill="x", padx=px(27, self.scale), pady=(0, px(9, self.scale)))
        left = tk.Frame(status, bg=theme.BG)
        left.pack(side="left")
        self.status_dot = tk.Canvas(
            left,
            width=px(9, self.scale),
            height=px(9, self.scale),
            bg=theme.BG,
            highlightthickness=0,
            bd=0,
        )
        self.status_dot.pack(side="left", padx=(0, px(7, self.scale)))
        self._dot = self.status_dot.create_oval(
            px(1, self.scale), px(1, self.scale), px(8, self.scale), px(8, self.scale),
            fill=theme.ACCENT, outline="",
        )
        self.status_text = tk.Label(
            left,
            text="正在启动监控…",
            bg=theme.BG,
            fg=theme.SUBTEXT,
            font=self.fonts["small"],
        )
        self.status_text.pack(side="left")
        self.foreground_label = tk.Label(
            left,
            text="",
            bg=theme.BG,
            fg=theme.FAINT,
            font=self.fonts["small"],
        )
        self.foreground_label.pack(side="left", padx=(px(16, self.scale), 0))

        right = tk.Frame(status, bg=theme.BG)
        right.pack(side="right")
        HoverButton(
            right,
            "设置",
            self.open_settings,
            bg=theme.BG,
            hover_bg=theme.CARD,
            fg=theme.SUBTEXT,
            hover_fg=theme.TEXT,
            font=self.fonts["small"],
            padx=px(8, self.scale),
            pady=px(3, self.scale),
        ).pack(side="right")
        self.last_scan = tk.Label(
            right,
            text="",
            bg=theme.BG,
            fg=theme.FAINT,
            font=self.fonts["small"],
        )
        self.last_scan.pack(side="right", padx=(0, px(6, self.scale)))

    # ------------------------------------------------------------------ tray
    def _setup_tray(self) -> None:
        self.tray = TrayManager(
            post=self._commands.put,
            on_show=self.show_window,
            on_settings=self.open_settings,
            on_quit=self.shutdown,
            on_toggle_enabled=self._toggle_enabled_from_tray,
            is_enabled=lambda: self.settings.enabled,
            counts=self._tray_counts,
        )
        if os.environ.get("QUIETFOCUS_NO_TRAY"):
            log.info("System tray disabled by environment")
            return
        self.tray.start()
        self._update_tray(force=True)

    def _tray_counts(self) -> tuple[int, int]:
        snapshot = self._snapshot
        if snapshot is None:
            return 0, 0
        selected = self.settings.selected_keys()
        running = {app.key for app in snapshot.apps}
        active = selected & running
        ready = self.settings.enabled and snapshot.foreground_ready
        controlled = len(active) if ready else 0
        muted = sum(1 for app in snapshot.apps if app.key in active and app.muted) if ready else 0
        return controlled, muted

    def _update_tray(self, force: bool = False) -> None:
        if not getattr(self, "tray", None) or not self.tray.available:
            return
        state = (self.settings.enabled, *self._tray_counts())
        if force or state != self._tray_state:
            self._tray_state = state
            self.tray.update()

    def _toggle_enabled_from_tray(self) -> None:
        self._toggle_enabled(not self.settings.enabled)

    # --------------------------------------------------------------- lifecycle
    def _show_initial_window(self) -> None:
        log.info(
            "Showing initial window (hidden=%s tray=%s geometry=%s)",
            self._start_hidden,
            self.tray.available,
            self.root.winfo_geometry(),
        )
        if self._start_hidden and self.tray.available:
            self.root.withdraw()
            if not self.settings.tray_hint_shown:
                self.tray.notify("静界已在后台运行，双击托盘图标可打开主界面。")
                self.settings.set_tray_hint_shown()
            return
        self.show_window()

    def show_window(self) -> None:
        if self._closing:
            return
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.focus_force()
            self.root.attributes("-topmost", True)
            self.root.after(120, lambda: self._safe_topmost_false())
            self.root.update_idletasks()
            log.info(
                "Window shown: state=%s viewable=%s geometry=%s",
                self.root.state(),
                self.root.winfo_viewable(),
                self.root.winfo_geometry(),
            )
        except tk.TclError as exc:
            log.warning("Could not show window: %s", exc)

    def _safe_topmost_false(self) -> None:
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

    def on_close(self) -> None:
        if self._closing:
            return
        log.info("Close requested (tray=%s close_to_tray=%s)", self.tray.available, self.settings.close_to_tray)
        if self.tray.available and self.settings.close_to_tray:
            self.root.withdraw()
            if not self.settings.tray_hint_shown:
                self.tray.notify("静界仍在后台监控，双击托盘图标可重新打开。关闭自动静音后才会恢复声音。")
                self.settings.set_tray_hint_shown()
            return
        self.shutdown()

    def shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        log.info("Shutting down")
        if self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.root.withdraw()
            self.root.update_idletasks()
        except Exception:
            pass
        try:
            # This also restores every session we muted.
            self._engine.stop()
        except Exception:
            log.exception("Audio engine stop failed")
        try:
            self.settings.save()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------ queue
    def _enqueue_snapshot(self, snapshot: EngineSnapshot) -> None:
        try:
            self._snapshot_queue.put_nowait(snapshot)
        except queue.Full:
            try:
                self._snapshot_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._snapshot_queue.put_nowait(snapshot)
            except queue.Full:
                pass

    def _poll(self) -> None:
        if self._closing:
            return
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                break
            try:
                command()
            except Exception:
                log.exception("Tray command failed")
        latest = None
        while True:
            try:
                latest = self._snapshot_queue.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self._render(latest)
        try:
            self._poll_id = self.root.after(110, self._poll)
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- actions
    def _toggle_enabled(self, value: bool) -> None:
        if self._closing:
            return
        self.settings.set_enabled(bool(value))
        self.master_switch.set_value(self.settings.enabled)
        self._update_master_label()
        self._engine.wake()
        self._update_tray(force=True)
        self._update_stats()

    def _update_master_label(self) -> None:
        if self.settings.enabled:
            self.master_status.configure(text="已开启", fg=theme.ACCENT_DARK)
        else:
            self.master_status.configure(text="已暂停", fg=theme.MUTED_FG)

    def _select_all(self) -> int:
        if self._snapshot is None:
            return 0
        self._cancel_auto_select()
        items = [
            (
                app.key,
                {"name": app.name, "exe_name": app.exe_name, "exe_path": app.exe_path},
            )
            for app in self._snapshot.apps
        ]
        changed = self.settings.select_all(items, clear_ignored=True)
        if changed:
            self._hide_banner()
            self._engine.wake()
            self._update_tray(force=True)
            self._update_rows_selection()
            self._update_stats()
        return changed

    def select_all(self) -> None:
        self._select_all()

    def clear_all(self) -> None:
        self._cancel_auto_select()
        running = {app.key for app in self._snapshot.apps} if self._snapshot else set()
        changed = self.settings.clear_all(running)
        if changed:
            self._hide_banner()
            self._engine.wake()
            self._update_tray(force=True)
            self._update_rows_selection()
            self._update_stats()
        elif running:
            self._update_rows_selection()
            self._update_stats()

    def _toggle_app(self, key: str, checked: bool) -> None:
        snapshot = self._snapshot
        meta = None
        if snapshot:
            for app in snapshot.apps:
                if app.key == key:
                    meta = {"name": app.name, "exe_name": app.exe_name, "exe_path": app.exe_path}
                    break
        self._cancel_auto_select()
        self.settings.set_app_selected(key, checked, meta)
        self._hide_banner()
        self._engine.wake()
        row = self._rows.get(key)
        if row is not None:
            row.set_selected(checked)
        self._update_tray(force=True)
        self._update_stats()

    def _update_rows_selection(self) -> None:
        for key, row in self._rows.items():
            row.set_selected(self.settings.is_selected(key))

    def refresh(self) -> None:
        self._engine.wake()
        try:
            self.status_text.configure(text="正在刷新音频会话…")
            self.status_dot.itemconfigure(self._dot, fill=theme.ACCENT)
        except tk.TclError:
            pass

    def _cancel_auto_select(self) -> None:
        if self._auto_select_pending:
            self._auto_select_pending = False
            self.settings.mark_onboarded()
            self.settings.save()

    def _auto_select_new_apps(self, apps: tuple[AppSnapshot, ...]) -> None:
        if not self.settings.enabled or not self.settings.auto_select_new:
            return
        selected = self.settings.selected_keys()
        ignored = self.settings.ignored_keys()
        new_items = [
            (
                app.key,
                {"name": app.name, "exe_name": app.exe_name, "exe_path": app.exe_path},
            )
            for app in apps
            if app.key not in selected and app.key not in ignored
        ]
        if not new_items:
            return
        added = self.settings.select_all(new_items)
        if added:
            log.info("Auto-selected %d new audio applications", added)
            self._engine.wake()
            self._update_tray(force=True)

    def _auto_select_current(self, apps: tuple[AppSnapshot, ...]) -> None:
        if not self._auto_select_pending:
            return
        if time.monotonic() > self._auto_select_deadline:
            self._auto_select_pending = False
            self.settings.mark_onboarded()
            self.settings.save()
            return
        items = [
            (
                app.key,
                {"name": app.name, "exe_name": app.exe_name, "exe_path": app.exe_path},
            )
            for app in apps
        ]
        changed = self.settings.select_all(items)
        self._auto_select_pending = False
        self.settings.mark_onboarded()
        self.settings.save()
        if changed:
            self._show_banner(
                f"首次使用：已勾选当前 {len(apps)} 个音频应用。取消勾选，即可让某个应用始终保持声音。"
            )
            self._engine.wake()
            self._update_tray(force=True)

    # ----------------------------------------------------------------- render
    def _render(self, snapshot: EngineSnapshot) -> None:
        if self._closing:
            return
        self._snapshot = snapshot
        if self._auto_select_pending and snapshot.apps:
            self._auto_select_current(snapshot.apps)
        self._auto_select_new_apps(snapshot.apps)

        apps = snapshot.apps
        keys = [app.key for app in apps]
        if keys != self._row_order:
            self._rebuild_rows(apps)
        selected = self.settings.selected_keys()
        for app in apps:
            row = self._rows.get(app.key)
            if row is not None:
                row.update(app, app.key in selected)

        if not apps:
            self.empty.grid()
            if snapshot.error:
                self.empty.set_error(snapshot.error)
            else:
                self.empty.set_loading(False)
            self.scroll.refresh()
        else:
            self.empty.grid_remove()

        self._update_stats()
        if snapshot.error:
            self.status_dot.itemconfigure(self._dot, fill=theme.DANGER)
            self.status_text.configure(text=snapshot.error)
        elif not snapshot.foreground_ready:
            self.status_dot.itemconfigure(self._dot, fill=theme.MUTED_FG)
            self.status_text.configure(text="等待前台应用…")
        else:
            self.status_dot.itemconfigure(
                self._dot, fill=theme.ACCENT if snapshot.enabled else theme.MUTED_FG
            )
            if snapshot.enabled:
                self.status_text.configure(
                    text=f"监控中 · 每 {self.settings.poll_interval:.1f} 秒扫描"
                )
            else:
                self.status_text.configure(text="自动静音已暂停")
        if not snapshot.foreground_ready:
            self.foreground_label.configure(text="当前前台：等待识别")
        elif snapshot.foreground_title:
            title = _shorten(snapshot.foreground_title, 44)
            self.foreground_label.configure(text=f"当前前台：{title}")
        elif snapshot.foreground_exe:
            self.foreground_label.configure(text=f"当前前台：{snapshot.foreground_exe}")
        else:
            self.foreground_label.configure(text="当前前台：桌面")
        self.last_scan.configure(text=f"更新于 {datetime.fromtimestamp(snapshot.at):%H:%M:%S}")
        self._update_tray()

    def _rebuild_rows(self, apps: tuple[AppSnapshot, ...]) -> None:
        new_keys = {app.key for app in apps}
        for key in list(self._rows):
            if key not in new_keys:
                self._rows.pop(key).destroy()
        selected = self.settings.selected_keys()
        for app in apps:
            if app.key not in self._rows:
                self._rows[app.key] = AppRow(
                    self.scroll.inner,
                    app,
                    app.key in selected,
                    self.icons,
                    self.fonts,
                    self._toggle_app,
                    scale=self.scale,
                )
        self._row_order = [app.key for app in apps]
        for index, key in enumerate(self._row_order):
            self._rows[key].frame.grid(row=index, column=0, sticky="ew")
        self.scroll.inner.grid_columnconfigure(0, weight=1)
        self.scroll.refresh()

    def _update_stats(self) -> None:
        snapshot = self._snapshot
        apps = snapshot.apps if snapshot else ()
        running = {app.key for app in apps}
        selected = self.settings.selected_keys()
        selected_running = selected & running
        enabled = self.settings.enabled
        ready = bool(snapshot and snapshot.foreground_ready)
        controlled = len(selected_running) if enabled and ready else 0
        muted = (
            sum(1 for app in apps if app.key in selected_running and app.muted)
            if enabled and ready
            else 0
        )

        if snapshot is None:
            self.count_chip.configure(text="扫描中")
            self.summary_label.configure(text="")
        else:
            self.count_chip.configure(text=f"{len(apps)} 个")
            if snapshot.error:
                self.summary_label.configure(text="读取失败")
            elif not enabled:
                self.summary_label.configure(text="监控已暂停")
            elif not selected_running:
                self.summary_label.configure(text="尚未选择应用")
            elif not ready:
                self.summary_label.configure(text="等待前台应用…")
            else:
                self.summary_label.configure(
                    text=f"已控制 {controlled} 个 · 已静音 {muted} 个"
                )

        missing = selected - running
        if missing:
            self.remembered_label.pack_forget()
            if not self.remembered_button.winfo_ismapped():
                self.remembered_button.pack(side="right")
            self.remembered_button.set_text(f"已记住 {len(missing)} 个当前未发声的应用")
        else:
            self.remembered_button.pack_forget()
            if not self.remembered_label.winfo_ismapped():
                self.remembered_label.pack(side="right")
            self.remembered_label.configure(text="设置已保存在本机")

        self.master_switch.set_value(enabled)
        self._update_master_label()
        self._update_tray()

    # ------------------------------------------------------------------ actions
    def _show_banner(self, text: str) -> None:
        self.banner_text.configure(text=text)
        if not self._banner_visible:
            try:
                self.banner.pack(fill="x", pady=(px(9, self.scale), 0), before=self.card)
                self._banner_visible = True
                log.debug("Banner shown: mapped=%s", self.banner.winfo_ismapped())
            except tk.TclError as exc:
                log.warning("Could not show banner: %s", exc)
                # Fall back to appending it below the toolbar.
                self.banner.pack(fill="x", pady=(px(9, self.scale), 0))
                self._banner_visible = True

    def _hide_banner(self) -> None:
        if self._banner_visible:
            self.banner.pack_forget()
            self._banner_visible = False

    def _manage_missing(self) -> None:
        snapshot = self._snapshot
        running = {app.key for app in snapshot.apps} if snapshot else set()
        missing = self.settings.selected_keys() - running
        if not missing:
            return
        if not messagebox.askyesno(
            "清除记忆",
            f"有 {len(missing)} 个已勾选的应用当前没有音频会话。\n"
            "清除后，这些应用下次发声时不会再被自动静音（除非重新勾选）。\n\n继续吗？",
            parent=self.root,
        ):
            return
        removed = self.settings.forget_missing(running)
        log.info("Cleared %d remembered apps", removed)
        self._engine.wake()
        self._update_stats()
        self._update_tray(force=True)

    # ---------------------------------------------------------------- settings
    def open_settings(self) -> None:
        if self._closing:
            return
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_force()
            return
        self._cancel_auto_select()
        dialog = tk.Toplevel(self.root)
        self._settings_window = dialog
        dialog.title("设置 · 静界 QuietFocus")
        dialog.configure(bg=theme.BG)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        try:
            dialog.iconbitmap(resource_path("assets", "icon.ico"))
        except Exception:
            pass
        width = px(540, self.scale)
        height = min(px(790, self.scale), int(self.root.winfo_screenheight() * 0.90))
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 3)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.protocol("WM_DELETE_WINDOW", self._close_settings)
        dialog.bind("<Escape>", lambda _e: self._close_settings())
        try:
            dialog.grab_set()
        except tk.TclError:
            pass

        outer = tk.Frame(dialog, bg=theme.BG)
        outer.pack(fill="both", expand=True, padx=px(22, self.scale), pady=px(18, self.scale))
        tk.Label(
            outer,
            text="设置",
            bg=theme.BG,
            fg=theme.TEXT,
            font=self.fonts["dialog_title"],
        ).pack(anchor="w")
        tk.Label(
            outer,
            text="调整静界的运行方式和扫描节奏。",
            bg=theme.BG,
            fg=theme.SUBTEXT,
            font=self.fonts["body"],
        ).pack(anchor="w", pady=(px(2, self.scale), px(13, self.scale)))

        general = self._settings_card(outer, "常规")
        self._autostart_switch = self._switch_row(
            general,
            "开机自动启动",
            "登录 Windows 后在后台自动运行静界。",
            self._safe_autostart_state(),
            self._toggle_autostart,
        )
        self._separator(general)
        self._switch_row(
            general,
            "新应用自动接管",
            "新出现的音频应用自动勾选；取消勾选后不会再自动接管。",
            self.settings.auto_select_new,
            self._set_auto_select_new,
        )
        self._separator(general)
        self._switch_row(
            general,
            "关闭窗口时最小化到托盘",
            "关闭按钮不退出程序，自动静音继续工作。",
            self.settings.close_to_tray,
            self._set_close_to_tray,
        )
        self._separator(general)
        self._switch_row(
            general,
            "启动时最小化到托盘",
            "程序启动后不显示主窗口。",
            self.settings.start_minimized,
            self._set_start_minimized,
        )
        self._separator(general)
        self._switch_row(
            general,
            "退出时恢复默认声音",
            "退出静界时将它控制过的应用全部取消静音，不留下静音状态。",
            self.settings.restore_on_exit,
            self._set_restore_on_exit,
        )

        detection = self._settings_card(outer, "扫描")
        interval_top = tk.Frame(detection, bg=theme.CARD)
        interval_top.pack(fill="x")
        tk.Label(
            interval_top,
            text="扫描间隔",
            bg=theme.CARD,
            fg=theme.TEXT,
            font=self.fonts["setting_title"],
        ).pack(side="left")
        self._interval_label = tk.Label(
            interval_top,
            text=f"{self.settings.poll_interval:.1f} 秒",
            bg=theme.CARD,
            fg=theme.ACCENT_DARK,
            font=self.fonts["button"],
        )
        self._interval_label.pack(side="right")
        tk.Label(
            detection,
            text="间隔越短，切到后台时静音越快，但会占用稍多 CPU。",
            bg=theme.CARD,
            fg=theme.SUBTEXT,
            font=self.fonts["setting_desc"],
            wraplength=px(440, self.scale),
            justify="left",
        ).pack(anchor="w", pady=(px(3, self.scale), px(4, self.scale)))
        self._interval_slider = Slider(
            detection,
            value=self.settings.poll_interval,
            minimum=MIN_INTERVAL,
            maximum=3.0,
            command=self._on_interval_preview,
            on_release=self._apply_interval,
            scale=self.scale,
            bg=theme.CARD,
        )
        self._interval_slider.pack(fill="x", pady=(px(2, self.scale), px(2, self.scale)))

        data_card = self._settings_card(outer, "数据")
        tk.Label(
            data_card,
            text=data_dir(),
            bg=theme.CARD,
            fg=theme.SUBTEXT,
            font=self.fonts["setting_desc"],
            wraplength=px(440, self.scale),
            justify="left",
        ).pack(anchor="w")
        buttons = tk.Frame(data_card, bg=theme.CARD)
        buttons.pack(fill="x", pady=(px(8, self.scale), 0))
        HoverButton(
            buttons,
            "打开数据目录",
            lambda: open_data_folder(data_dir()),
            bg=theme.ACCENT_SOFT,
            hover_bg=theme.ACCENT_SOFT_2,
            fg=theme.ACCENT_DARK,
            font=self.fonts["button"],
            padx=px(12, self.scale),
            pady=px(5, self.scale),
        ).pack(side="left")
        missing = self._missing_count()
        self._clear_missing_button = HoverButton(
            buttons,
            f"清除未发声记录 ({missing})" if missing else "没有未发声记录",
            self._clear_missing_from_dialog,
            bg=theme.CARD,
            hover_bg=theme.IDLE_BG,
            fg=theme.SUBTEXT,
            font=self.fonts["button"],
            padx=px(12, self.scale),
            pady=px(5, self.scale),
        )
        self._clear_missing_button.pack(side="right")
        self._clear_missing_button.set_enabled(bool(missing))

        bottom = tk.Frame(outer, bg=theme.BG)
        bottom.pack(fill="x", side="bottom", pady=(px(12, self.scale), 0))
        HoverButton(
            bottom,
            "完成",
            self._close_settings,
            bg=theme.ACCENT,
            hover_bg=theme.ACCENT_DARK,
            fg=theme.WHITE,
            hover_fg=theme.WHITE,
            font=self.fonts["button"],
            padx=px(24, self.scale),
            pady=px(8, self.scale),
        ).pack(side="right")
        tk.Label(
            bottom,
            text="设置会自动保存",
            bg=theme.BG,
            fg=theme.FAINT,
            font=self.fonts["small"],
        ).pack(side="right", padx=(0, px(12, self.scale)))

    def _settings_card(self, parent, title: str) -> tk.Frame:
        wrapper = tk.Frame(
            parent,
            bg=theme.CARD,
            highlightbackground=theme.BORDER,
            highlightthickness=1,
        )
        wrapper.pack(fill="x", pady=(0, px(11, self.scale)))
        tk.Label(
            wrapper,
            text=title,
            bg=theme.CARD,
            fg=theme.FAINT,
            font=self.fonts["small"],
        ).pack(anchor="w", padx=px(15, self.scale), pady=(px(10, self.scale), px(4, self.scale)))
        inner = tk.Frame(wrapper, bg=theme.CARD)
        inner.pack(fill="x", padx=px(15, self.scale), pady=(0, px(11, self.scale)))
        return inner

    def _switch_row(
        self,
        parent,
        title: str,
        description: str,
        value: bool,
        command: Callable[[bool], None],
    ) -> ToggleSwitch:
        row = tk.Frame(parent, bg=theme.CARD)
        row.pack(fill="x", pady=px(4, self.scale))
        text = tk.Frame(row, bg=theme.CARD)
        text.pack(side="left", fill="x", expand=True)
        tk.Label(
            text,
            text=title,
            bg=theme.CARD,
            fg=theme.TEXT,
            font=self.fonts["setting_title"],
        ).pack(anchor="w")
        tk.Label(
            text,
            text=description,
            bg=theme.CARD,
            fg=theme.SUBTEXT,
            font=self.fonts["setting_desc"],
            wraplength=px(350, self.scale),
            justify="left",
        ).pack(anchor="w", pady=(px(1, self.scale), 0))
        switch = ToggleSwitch(
            row,
            value,
            command,
            scale=self.scale,
            bg=theme.CARD,
        )
        switch.pack(side="right", padx=(px(10, self.scale), 0))
        return switch

    def _separator(self, parent) -> None:
        tk.Frame(parent, bg=theme.BORDER, height=1).pack(fill="x", pady=px(7, self.scale))

    def _safe_autostart_state(self) -> bool:
        try:
            return is_autostart_enabled()
        except OSError:
            return bool(get_autostart_command())

    def _toggle_autostart(self, value: bool) -> None:
        try:
            set_autostart(value)
        except OSError as exc:
            log.warning("Autostart change failed: %s", exc)
            if self._autostart_switch is not None:
                self._autostart_switch.set_value(not value)
            messagebox.showerror(
                "设置开机启动失败",
                "无法写入当前用户的启动项。\n"
                "请确认系统允许修改 HKEY_CURRENT_USER 的 Run 键。",
                parent=self._settings_window or self.root,
            )

    def _set_auto_select_new(self, value: bool) -> None:
        self.settings.set_auto_select_new(value)
        if value and self._snapshot is not None:
            self._auto_select_new_apps(self._snapshot.apps)
            self._update_rows_selection()
            self._update_stats()

    def _set_close_to_tray(self, value: bool) -> None:
        self.settings.set_close_to_tray(value)

    def _set_start_minimized(self, value: bool) -> None:
        self.settings.set_start_minimized(value)

    def _set_restore_on_exit(self, value: bool) -> None:
        self.settings.set_restore_on_exit(value)

    def _on_interval_preview(self, value: float) -> None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if hasattr(self, "_interval_label"):
            try:
                self._interval_label.configure(text=f"{number:.1f} 秒")
            except tk.TclError:
                return
        if self._last_interval_apply is not None:
            try:
                self.root.after_cancel(self._last_interval_apply)
            except Exception:
                pass
        self._last_interval_apply = self.root.after(
            260, lambda: self._apply_interval(number)
        )

    def _apply_interval(self, value: float) -> None:
        self._last_interval_apply = None
        self.settings.set_poll_interval(float(value))
        self._engine.wake()
        if self._snapshot and not self._snapshot.error:
            self.status_text.configure(
                text=f"监控中 · 每 {self.settings.poll_interval:.1f} 秒扫描"
            )

    def _missing_count(self) -> int:
        if self._snapshot is None:
            return 0
        running = {app.key for app in self._snapshot.apps}
        return len(self.settings.selected_keys() - running)

    def _clear_missing_from_dialog(self) -> None:
        if self._snapshot is None:
            return
        running = {app.key for app in self._snapshot.apps}
        missing = self.settings.selected_keys() - running
        if not missing:
            return
        if not messagebox.askyesno(
            "清除记忆",
            f"清除 {len(missing)} 个当前没有音频会话的应用记录？",
            parent=self._settings_window or self.root,
        ):
            return
        self.settings.forget_missing(running)
        self._engine.wake()
        self._update_stats()
        if hasattr(self, "_clear_missing_button"):
            self._clear_missing_button.set_text("没有未发声记录")
            self._clear_missing_button.set_enabled(False)
        self._update_tray(force=True)

    def _close_settings(self) -> None:
        dialog = self._settings_window
        self._settings_window = None
        if dialog is not None:
            try:
                dialog.grab_release()
            except tk.TclError:
                pass
            try:
                dialog.destroy()
            except tk.TclError:
                pass
        self._interval_slider = None
        self._autostart_switch = None
        self._last_interval_apply = None

    # -------------------------------------------------------------------- run
    def run(self) -> None:
        self.root.mainloop()


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
