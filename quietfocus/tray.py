"""System tray integration (optional, pystray based)."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from .ui.icons import tray_image

log = logging.getLogger(__name__)


class TrayManager:
    def __init__(
        self,
        *,
        post: Callable[[Callable[[], None]], None],
        on_show: Callable[[], None],
        on_settings: Callable[[], None],
        on_quit: Callable[[], None],
        on_toggle_enabled: Callable[[], None],
        is_enabled: Callable[[], bool],
        counts: Callable[[], tuple[int, int]],
    ) -> None:
        self._post = post
        self._on_show = on_show
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._on_toggle_enabled = on_toggle_enabled
        self._is_enabled = is_enabled
        self._counts = counts
        self._icon = None
        self.available = False
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._error: Exception | None = None

    def start(self) -> bool:
        try:
            import pystray
        except Exception as exc:
            log.warning("System tray unavailable: %s", exc)
            return False
        try:
            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", self._show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    lambda _item: "自动静音：已开启" if self._is_enabled() else "自动静音：已暂停",
                    self._toggle,
                    checked=lambda _item: self._is_enabled(),
                ),
                pystray.MenuItem(self._status_text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("设置…", self._settings),
                pystray.MenuItem("退出并恢复声音", self._quit),
            )
            icon = pystray.Icon(
                "QuietFocus",
                tray_image(),
                "静界 QuietFocus",
                menu,
            )
            self._icon = icon

            def setup(tray_icon) -> None:
                tray_icon.visible = True
                self._ready.set()

            def runner() -> None:
                try:
                    icon.run(setup=setup)
                except Exception as exc:  # pragma: no cover - platform specific
                    self._error = exc
                    log.warning("Could not start system tray: %s", exc)
                finally:
                    self._ready.set()

            threading.Thread(target=runner, name="QuietFocusTray", daemon=True).start()
            self._ready.wait(1.2)
            if self._error is not None or not getattr(icon, "visible", False):
                self.available = False
                self._icon = None
                try:
                    icon.stop()
                except Exception:
                    pass
                return False
            self.available = True
            log.info("System tray started")
            return True
        except Exception as exc:
            log.warning("Could not start system tray: %s", exc)
            self._icon = None
            self.available = False
            return False

    def _status_text(self, _item=None) -> str:
        controlled, muted = self._counts()
        if controlled == 0:
            return "尚未选择应用"
        return f"正在控制 {controlled} 个 · 已静音 {muted} 个"

    def _show(self, _icon=None, _item=None) -> None:
        self._post(self._on_show)

    def _settings(self, _icon=None, _item=None) -> None:
        self._post(self._on_settings)

    def _quit(self, _icon=None, _item=None) -> None:
        self._post(self._on_quit)

    def _toggle(self, _icon=None, _item=None) -> None:
        self._post(self._on_toggle_enabled)

    def update(self) -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.update_menu()
        except Exception:
            pass

    def notify(self, message: str, title: str = "静界 QuietFocus") -> None:
        icon = self._icon
        if icon is None:
            return
        try:
            icon.notify(message, title)
        except Exception as exc:
            log.debug("Tray notification failed: %s", exc)

    def stop(self) -> None:
        icon = self._icon
        self._icon = None
        self.available = False
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
