"""Developer-only screenshot harness for QuietFocus windows."""

from __future__ import annotations

import os
import sys
import time

from PIL import ImageGrab

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quietfocus.ui.main_window import QuietFocusApp  # noqa: E402
from quietfocus.winutil import set_dpi_awareness  # noqa: E402


def _capture_widget(widget, output: str) -> None:
    widget.update_idletasks()
    widget.update()
    time.sleep(0.35)
    x = widget.winfo_rootx()
    y = widget.winfo_rooty()
    w = widget.winfo_width()
    h = widget.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(output)
    print("saved", output, (w, h))


def main() -> None:
    set_dpi_awareness()
    output = os.path.abspath(os.environ.get("QUIETFOCUS_PREVIEW_OUT", "preview.png"))
    show_settings = bool(os.environ.get("QUIETFOCUS_PREVIEW_SETTINGS"))
    show_banner = bool(os.environ.get("QUIETFOCUS_PREVIEW_BANNER"))
    app = QuietFocusApp(start_minimized=False)

    def capture() -> None:
        app.show_window()
        app.root.attributes("-topmost", True)
        app.root.lift()
        app.root.update_idletasks()
        app.root.update()
        if show_banner:
            app._show_banner(
                "首次使用：已勾选当前 5 个音频应用。取消勾选，即可让某个应用始终保持声音。"
            )
            app.root.update_idletasks()
            print(
                "banner mapped:",
                app.banner.winfo_ismapped(),
                "size:",
                app.banner.winfo_width(),
                app.banner.winfo_height(),
            )
        if show_settings:
            app.open_settings()
            app.root.update_idletasks()
            app.root.update()
            dialog = app._settings_window
            if dialog is not None:
                time.sleep(0.5)
                _capture_widget(dialog, output)
        else:
            time.sleep(0.5)
            app.root.update_idletasks()
            app.root.update()
            x = app.root.winfo_rootx()
            y = app.root.winfo_rooty()
            w = app.root.winfo_width()
            h = app.root.winfo_height()
            ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(output)
            print("saved", output, (w, h))
        try:
            app.root.attributes("-topmost", False)
        except Exception:
            pass
        app.root.after(250, app.shutdown)

    app.root.after(2000, capture)
    app.run()


if __name__ == "__main__":
    main()
