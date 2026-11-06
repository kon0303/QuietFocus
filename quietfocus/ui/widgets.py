"""Custom Tk widgets used by the QuietFocus interface."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from ..audio import AppSnapshot
from . import theme
from .icons import IconProvider


def px(value: float, scale: float) -> int:
    return max(1, round(value * scale))


class HoverButton(tk.Label):
    def __init__(
        self,
        master,
        text: str,
        command: Callable[[], None],
        *,
        bg: str = theme.BG,
        hover_bg: str = theme.CARD,
        fg: str = theme.SUBTEXT,
        hover_fg: str | None = None,
        font=None,
        padx: int = 10,
        pady: int = 5,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            text=text,
            bg=bg,
            fg=fg,
            font=font,
            padx=padx,
            pady=pady,
            cursor="hand2",
            takefocus=1,
            highlightthickness=0,
            bd=0,
            **kwargs,
        )
        self._command = command
        self._bg = bg
        self._hover_bg = hover_bg
        self._fg = fg
        self._hover_fg = hover_fg or fg
        self._enabled = True
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Return>", self._on_click)
        self.bind("<space>", self._on_click)

    def _on_enter(self, _event=None) -> None:
        if self._enabled:
            self.configure(bg=self._hover_bg, fg=self._hover_fg)

    def _on_leave(self, _event=None) -> None:
        if self._enabled:
            self.configure(bg=self._bg, fg=self._fg)

    def _on_click(self, _event=None) -> None:
        if self._enabled:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(
            cursor="hand2" if enabled else "arrow",
            fg=self._fg if enabled else theme.FAINT,
        )

    def set_text(self, text: str) -> None:
        self.configure(text=text)


class CheckBox(tk.Canvas):
    def __init__(
        self,
        master,
        checked: bool,
        command: Callable[[bool], None],
        icons: IconProvider,
        *,
        bg: str = theme.CARD,
    ) -> None:
        self._checked = bool(checked)
        self._command = command
        self._icons = icons
        image = icons.checkbox(self._checked)
        self._size = image.width() + 2
        super().__init__(
            master,
            width=self._size,
            height=self._size,
            bg=bg,
            highlightthickness=1,
            highlightbackground=bg,
            highlightcolor=theme.ACCENT,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self._item = self.create_image(self._size // 2, self._size // 2, image=image)
        self.bind("<Button-1>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<Return>", self._toggle)

    def _toggle(self, _event=None) -> None:
        self._checked = not self._checked
        self._icons.checkbox(self._checked)
        self.itemconfigure(self._item, image=self._icons.checkbox(self._checked))
        self._command(self._checked)

    def set_checked(self, checked: bool) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self.itemconfigure(self._item, image=self._icons.checkbox(checked))

    def set_background(self, color: str) -> None:
        self.configure(bg=color, highlightbackground=color)

    @property
    def checked(self) -> bool:
        return self._checked


class ToggleSwitch(tk.Canvas):
    def __init__(
        self,
        master,
        value: bool,
        command: Callable[[bool], None],
        *,
        scale: float = 1.0,
        bg: str = theme.CARD,
    ) -> None:
        self._scale = scale
        self._value = bool(value)
        self._command = command
        self._bg = bg
        self._switch_w = px(46, scale)
        self._switch_h = px(26, scale)
        super().__init__(
            master,
            width=self._switch_w,
            height=self._switch_h,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
            takefocus=1,
        )
        self.bind("<Button-1>", self._toggle)
        self.bind("<space>", self._toggle)
        self.bind("<Return>", self._toggle)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w, h = self._switch_w, self._switch_h
        track = theme.ACCENT if self._value else "#D5DFDB"
        radius = h / 2
        self.create_oval(0, 0, h, h, fill=track, outline=track)
        self.create_oval(w - h, 0, w, h, fill=track, outline=track)
        self.create_rectangle(h / 2, 0, w - h / 2, h, fill=track, outline=track)
        pad = px(3, self._scale)
        knob = h - pad * 2
        x = w - pad - knob if self._value else pad
        self.create_oval(
            x,
            pad,
            x + knob,
            pad + knob,
            fill=theme.WHITE,
            outline="#EAF0ED" if not self._value else theme.WHITE,
            width=1,
        )

    def _toggle(self, _event=None) -> None:
        self._value = not self._value
        self._draw()
        self._command(self._value)

    def set_value(self, value: bool) -> None:
        value = bool(value)
        if value == self._value:
            return
        self._value = value
        self._draw()

    @property
    def value(self) -> bool:
        return self._value


class Slider(tk.Canvas):
    """A small themed slider used by the settings dialog."""

    def __init__(
        self,
        master,
        value: float,
        minimum: float,
        maximum: float,
        command: Callable[[float], None] | None = None,
        *,
        on_release: Callable[[float], None] | None = None,
        scale: float = 1.0,
        bg: str = theme.CARD,
    ) -> None:
        self._scale = scale
        self._min = float(minimum)
        self._max = float(maximum)
        self._value = max(self._min, min(self._max, float(value)))
        self._command = command
        self._on_release = on_release
        self._height = px(30, scale)
        super().__init__(
            master,
            height=self._height,
            bg=bg,
            highlightthickness=0,
            bd=0,
            takefocus=1,
        )
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_up)
        self.bind("<Left>", lambda _e: self._nudge(-0.1))
        self.bind("<Right>", lambda _e: self._nudge(0.1))
        self._draw()

    def set_value(self, value: float) -> None:
        self._value = max(self._min, min(self._max, float(value)))
        self._draw()

    @property
    def value(self) -> float:
        return self._value

    def _track_bounds(self) -> tuple[float, float]:
        pad = px(9, self._scale)
        return pad, max(pad + 1, self.winfo_width() - pad)

    def _draw(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        if width <= 1:
            width = px(300, self._scale)
        left, right = self._track_bounds()
        y = self._height / 2
        track_h = px(6, self._scale)
        radius = track_h / 2
        # Background track.
        self._rounded_rect(left, y - track_h / 2, right, y + track_h / 2, radius, "#E2EBE7")
        ratio = (self._value - self._min) / (self._max - self._min)
        knob_x = left + (right - left) * ratio
        if knob_x > left + 1:
            self._rounded_rect(
                left, y - track_h / 2, knob_x, y + track_h / 2, radius, theme.ACCENT
            )
        knob_r = px(8, self._scale)
        self.create_oval(
            knob_x - knob_r,
            y - knob_r,
            knob_x + knob_r,
            y + knob_r,
            fill=theme.WHITE,
            outline=theme.ACCENT,
            width=max(2, px(2, self._scale)),
        )

    def _rounded_rect(self, x1, y1, x2, y2, radius, fill) -> None:
        radius = max(0, min(radius, (y2 - y1) / 2, (x2 - x1) / 2))
        self.create_oval(x1, y1, x1 + radius * 2, y2, fill=fill, outline="")
        self.create_oval(x2 - radius * 2, y1, x2, y2, fill=fill, outline="")
        self.create_rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline="")

    def _value_at(self, x: int) -> float:
        left, right = self._track_bounds()
        ratio = (x - left) / max(1, right - left)
        ratio = max(0.0, min(1.0, ratio))
        raw = self._min + ratio * (self._max - self._min)
        return round(raw * 10) / 10

    def _set_from_x(self, x: int, release: bool = False) -> None:
        value = self._value_at(x)
        if value != self._value:
            self._value = value
            self._draw()
            if self._command is not None:
                self._command(value)
        if release and self._on_release is not None:
            self._on_release(self._value)

    def _on_click(self, event) -> None:
        self.focus_set()
        self._set_from_x(event.x)

    def _on_drag(self, event) -> None:
        self._set_from_x(event.x)

    def _on_up(self, event) -> None:
        self._set_from_x(event.x, release=True)

    def _nudge(self, delta: float) -> None:
        self.set_value(self._value + delta)
        if self._command is not None:
            self._command(self._value)
        if self._on_release is not None:
            self._on_release(self._value)


class ScrollableFrame(tk.Frame):
    def __init__(self, master, *, bg: str = theme.CARD) -> None:
        super().__init__(master, bg=bg)
        self.canvas = tk.Canvas(
            self,
            bg=bg,
            highlightthickness=0,
            bd=0,
            yscrollincrement=24,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar = tk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            width=10,
            bg=bg,
            troughcolor=bg,
            activebackground=theme.BORDER_STRONG,
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        self.vbar.grid(row=0, column=1, sticky="ns", padx=(0, 4))
        self.vbar.grid_remove()
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner.grid_columnconfigure(0, weight=1)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self._updating_scrollbar = False
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_scroll(self, first: str, last: str) -> None:
        self.vbar.set(first, last)

    def _on_inner_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._update_scrollbar()

    def _update_scrollbar(self) -> None:
        if self._updating_scrollbar:
            return
        self._updating_scrollbar = True
        try:
            needed = self.inner.winfo_reqheight()
            visible = self.canvas.winfo_height()
            if needed > visible + 2:
                self.vbar.grid()
            else:
                self.vbar.grid_remove()
                self.canvas.yview_moveto(0)
        finally:
            self._updating_scrollbar = False

    def refresh(self) -> None:
        self.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_scrollbar()

    def scroll(self, units: int) -> None:
        if self.inner.winfo_reqheight() > self.canvas.winfo_height() + 2:
            self.canvas.yview_scroll(units, "units")


class AppRow:
    def __init__(
        self,
        parent,
        app: AppSnapshot,
        selected: bool,
        icons: IconProvider,
        fonts: dict[str, tuple],
        on_toggle: Callable[[str, bool], None],
        *,
        scale: float = 1.0,
    ) -> None:
        self.app = app
        self.key = app.key
        self._icons = icons
        self._fonts = fonts
        self._on_toggle = on_toggle
        self._scale = scale
        self._last_state: tuple | None = None
        self._bg_widgets: list[tk.Widget] = []

        self.frame = tk.Frame(parent, bg=theme.CARD)
        self.frame.grid_columnconfigure(0, minsize=px(49, scale))
        self.frame.grid_columnconfigure(1, minsize=px(42, scale))
        self.frame.grid_columnconfigure(2, weight=1)
        self.frame.grid_columnconfigure(3, minsize=px(74, scale))
        self.frame.grid_columnconfigure(4, minsize=px(70, scale))

        content = tk.Frame(self.frame, bg=theme.CARD)
        content.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(px(10, scale), px(10, scale)))
        content.grid_columnconfigure(0, minsize=px(49, scale))
        content.grid_columnconfigure(1, minsize=px(42, scale))
        content.grid_columnconfigure(2, weight=1)
        content.grid_columnconfigure(3, minsize=px(74, scale))
        content.grid_columnconfigure(4, minsize=px(70, scale))
        self._content = content

        self.checkbox = CheckBox(
            content, selected, self._checkbox_changed, icons, bg=theme.CARD
        )
        self.checkbox.grid(row=0, column=0, sticky="w", padx=(px(16, scale), px(10, scale)))

        self.icon_label = tk.Label(content, bg=theme.CARD, bd=0)
        self.icon_label.image = icons.app_icon(
            app.exe_path, app.exe_name, app.name, size=px(31, scale)
        )
        self.icon_label.configure(image=self.icon_label.image)
        self.icon_label.grid(row=0, column=1, sticky="w", padx=(0, px(11, scale)))

        text_frame = tk.Frame(content, bg=theme.CARD)
        text_frame.grid(row=0, column=2, sticky="ew")
        text_frame.grid_columnconfigure(0, weight=1)
        self.name_label = tk.Label(
            text_frame,
            text="",
            bg=theme.CARD,
            fg=theme.TEXT,
            font=fonts["app_name"],
            anchor="w",
            justify="left",
        )
        self.name_label.grid(row=0, column=0, sticky="ew")
        self.detail_label = tk.Label(
            text_frame,
            text="",
            bg=theme.CARD,
            fg=theme.SUBTEXT,
            font=fonts["detail"],
            anchor="w",
            justify="left",
        )
        self.detail_label.grid(row=1, column=0, sticky="ew", pady=(px(2, scale), 0))

        self.chip = tk.Label(
            content,
            text="",
            bg=theme.IDLE_BG,
            fg=theme.IDLE_FG,
            font=fonts["chip"],
            padx=px(8, scale),
            pady=px(3, scale),
            bd=0,
        )
        self.chip.grid(row=0, column=3, sticky="e", padx=(px(8, scale), px(8, scale)))

        self.sound_label = tk.Label(
            content,
            text="",
            bg=theme.CARD,
            fg=theme.SUBTEXT,
            font=fonts["sound"],
            anchor="e",
            width=6,
        )
        self.sound_label.grid(row=0, column=4, sticky="e", padx=(0, px(20, scale)))

        self.separator = tk.Frame(self.frame, bg="#EEF3F1", height=1)
        self.separator.grid(row=1, column=0, columnspan=5, sticky="ew", padx=px(16, scale))

        self._bg_widgets = [
            content,
            text_frame,
            self.name_label,
            self.detail_label,
            self.icon_label,
            self.sound_label,
        ]
        for widget in [content, text_frame, self.name_label, self.detail_label, self.icon_label, self.sound_label]:
            widget.bind("<Enter>", self._hover_on, add="+")
            widget.bind("<Leave>", self._hover_off, add="+")
            widget.bind("<Double-Button-1>", self._double_click, add="+")
        self.frame.bind("<Enter>", self._hover_on, add="+")
        self.frame.bind("<Leave>", self._hover_off, add="+")

        self.update(app, selected, force=True)

    def _hover_on(self, _event=None) -> None:
        for widget in self._bg_widgets:
            try:
                widget.configure(bg=theme.HOVER)
            except tk.TclError:
                pass
        self.checkbox.set_background(theme.HOVER)

    def _hover_off(self, _event=None) -> None:
        for widget in self._bg_widgets:
            try:
                widget.configure(bg=theme.CARD)
            except tk.TclError:
                pass
        self.checkbox.set_background(theme.CARD)

    def _double_click(self, _event=None) -> None:
        self.checkbox._toggle()

    def _checkbox_changed(self, checked: bool) -> None:
        self._on_toggle(self.key, checked)

    def set_selected(self, selected: bool) -> None:
        self.checkbox.set_checked(selected)

    def update(self, app: AppSnapshot, selected: bool, force: bool = False) -> None:
        chip_text, chip_bg, chip_fg = self._chip_state(app)
        if not app.active:
            sound_text, sound_fg = "—", theme.FAINT
        elif app.muted:
            sound_text, sound_fg = "已静音", theme.MUTED_FG
        else:
            sound_text, sound_fg = "发声", theme.SUBTEXT

        detail_parts = [app.exe_name or "未知进程"]
        if app.session_count > 1:
            detail_parts.append(f"{app.session_count} 个会话")
        if app.pids:
            detail_parts.append(f"PID {app.pids[0]}")
        detail = "  ·  ".join(detail_parts)

        name = _truncate(app.name or app.exe_name or "未知应用", 30)
        state = (
            name,
            detail,
            chip_text,
            chip_bg,
            chip_fg,
            sound_text,
            sound_fg,
            selected,
            app.exe_path,
            app.exe_name,
        )
        if not force and state == self._last_state:
            return
        self._last_state = state
        self.app = app
        self.name_label.configure(text=name)
        self.detail_label.configure(text=detail)
        self.chip.configure(text=chip_text, bg=chip_bg, fg=chip_fg)
        self.sound_label.configure(text=sound_text, fg=sound_fg)
        self.checkbox.set_checked(selected)
        icon_key = getattr(self, "_icon_key", None)
        new_icon_key = (app.exe_path.casefold(), app.exe_name.casefold(), app.name.casefold())
        if force or icon_key != new_icon_key:
            self._icon_key = new_icon_key
            self.icon_label.image = self._icons.app_icon(
                app.exe_path, app.exe_name, app.name, size=px(31, self._scale)
            )
            self.icon_label.configure(image=self.icon_label.image)

    @staticmethod
    def _chip_state(app: AppSnapshot) -> tuple[str, str, str]:
        if not app.active:
            return "待机", theme.IDLE_BG, theme.IDLE_FG
        if app.is_foreground:
            return "前台", theme.FOREGROUND_BG, theme.FOREGROUND_FG
        if app.controlled:
            return "后台", theme.BACKGROUND_BG, theme.BACKGROUND_FG
        return "后台", theme.IDLE_BG, theme.IDLE_FG

    def destroy(self) -> None:
        self.frame.destroy()


class EmptyState(tk.Frame):
    def __init__(
        self,
        master,
        fonts: dict[str, tuple],
        command: Callable[[], None],
        *,
        scale: float = 1.0,
    ) -> None:
        super().__init__(master, bg=theme.CARD)
        self._fonts = fonts
        self._command = command
        self._scale = scale

        self.art = tk.Canvas(
            self, width=px(86, scale), height=px(86, scale), bg=theme.CARD,
            highlightthickness=0, bd=0,
        )
        self.art.pack(pady=(px(48, scale), px(12, scale)))
        self._draw_art()

        self.title = tk.Label(
            self,
            text="正在扫描音频会话…",
            bg=theme.CARD,
            fg=theme.TEXT,
            font=fonts["empty_title"],
        )
        self.title.pack()
        self.subtitle = tk.Label(
            self,
            text="请稍候",
            bg=theme.CARD,
            fg=theme.SUBTEXT,
            font=fonts["body"],
            wraplength=px(420, scale),
            justify="center",
        )
        self.subtitle.pack(pady=(px(7, scale), px(16, scale)))
        self.button = HoverButton(
            self,
            text="重新扫描",
            command=command,
            bg=theme.ACCENT_SOFT,
            hover_bg=theme.ACCENT_SOFT_2,
            fg=theme.ACCENT_DARK,
            font=fonts["button"],
            padx=px(16, scale),
            pady=px(7, scale),
        )
        self.button.pack()
        self._loading = True

    def _draw_art(self) -> None:
        s = self._scale
        c = self.art
        c.create_oval(px(3, s), px(3, s), px(83, s), px(83, s), fill=theme.ACCENT_SOFT, outline="")
        c.create_oval(px(16, s), px(16, s), px(70, s), px(70, s), fill=theme.WHITE, outline="")
        # Speaker body and cone.
        c.create_rectangle(px(32, s), px(38, s), px(41, s), px(51, s), fill=theme.ACCENT, outline="")
        c.create_polygon(
            px(41, s), px(38, s), px(51, s), px(30, s), px(51, s), px(59, s), px(41, s), px(51, s),
            fill=theme.ACCENT, outline="",
        )
        c.create_arc(
            px(47, s), px(31, s), px(65, s), px(58, s),
            start=-55, extent=110, style="arc", outline=theme.ACCENT, width=max(2, px(2, s)),
        )
        c.create_arc(
            px(51, s), px(24, s), px(74, s), px(65, s),
            start=-52, extent=104, style="arc", outline="#79CFC2", width=max(2, px(2, s)),
        )

    def set_loading(self, loading: bool, count: int = 0) -> None:
        if loading:
            self.title.configure(text="正在扫描音频会话…", fg=theme.TEXT)
            self.subtitle.configure(text="正在读取 Windows 音量合成器", fg=theme.SUBTEXT)
            self.button.pack_forget()
        else:
            self.title.configure(text="暂无音频会话", fg=theme.TEXT)
            self.subtitle.configure(
                text="打开一个正在播放声音的应用，它会自动出现在这里。\n勾选左侧方框后，应用切到后台时会自动静音。",
                fg=theme.SUBTEXT,
            )
            self.button.pack()
        self._loading = loading

    def set_error(self, message: str) -> None:
        self.title.configure(text="无法读取音频会话", fg=theme.DANGER)
        self.subtitle.configure(text=message, fg=theme.SUBTEXT)
        self.button.pack()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"
