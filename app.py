"""QuietFocus entry point."""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys

from quietfocus.logging_setup import configure_logging
from quietfocus.winutil import (
    acquire_single_instance,
    close_show_event,
    create_show_event,
    message_box,
    refresh_autostart_path,
    release_single_instance,
    set_dpi_awareness,
    signal_show_existing,
)

log = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="静界 QuietFocus")
    parser.add_argument("--minimized", action="store_true", help="启动后隐藏主窗口")
    parser.add_argument("--debug", action="store_true", help="输出调试日志")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    set_dpi_awareness()
    configure_logging(debug=args.debug)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "QuietFocus.Desktop.1"
        )
    except Exception:
        pass

    mutex = acquire_single_instance()
    if mutex is None:
        log.info("Another instance is already running; asking it to show")
        if not signal_show_existing():
            message_box(
                "静界已经在运行。\n\n请查看任务栏或系统托盘中的静界图标。",
                "静界 QuietFocus",
            )
        return 0

    show_event = create_show_event()
    app = None
    try:
        refresh_autostart_path()
        from quietfocus.ui.main_window import QuietFocusApp

        app = QuietFocusApp(
            start_minimized=args.minimized,
            show_event=show_event,
        )
        app.run()
        return 0
    except Exception as exc:
        log.exception("Fatal error")
        message_box(
            f"静界启动失败：\n{exc}\n\n详细信息已写入日志：\n"
            f"{os.path.join(os.environ.get('APPDATA', ''), 'QuietFocus', 'quietfocus.log')}",
            "静界 QuietFocus",
            error=True,
        )
        return 1
    finally:
        if app is not None:
            try:
                if not app._closing:
                    app.shutdown()
            except Exception:
                pass
        close_show_event(show_event)
        release_single_instance(mutex)


if __name__ == "__main__":
    sys.exit(main())
