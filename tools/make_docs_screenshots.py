"""Render documentation screenshots with real widgets and sample data."""

from __future__ import annotations

import os
import sys
import time

from PIL import ImageGrab

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quietfocus.audio import AppSnapshot, EngineSnapshot  # noqa: E402
from quietfocus.ui.main_window import QuietFocusApp  # noqa: E402
from quietfocus.winutil import set_dpi_awareness  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def key_for(path: str) -> str:
    return "path:" + os.path.normcase(os.path.normpath(path))


def app(
    name: str,
    exe_name: str,
    path: str,
    pid: int,
    *,
    foreground: bool,
    selected: bool,
    muted: bool,
) -> AppSnapshot:
    return AppSnapshot(
        key=key_for(path),
        name=name,
        exe_name=exe_name,
        exe_path=path,
        pids=(pid,),
        session_count=1,
        is_foreground=foreground,
        selected=selected,
        controlled=selected,
        muted=muted,
        active=True,
    )


def sample_apps() -> tuple[AppSnapshot, ...]:
    return (
        app(
            "Microsoft Edge",
            "msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            42716,
            foreground=True,
            selected=True,
            muted=False,
        ),
        app(
            "Spotify",
            "Spotify.exe",
            os.path.join(
                os.environ.get("APPDATA", r"C:\Users\Public"),
                "Spotify",
                "Spotify.exe",
            ),
            31840,
            foreground=False,
            selected=True,
            muted=True,
        ),
        app(
            "Steam Client WebHelper",
            "steamwebhelper.exe",
            r"D:\Steam\bin\cef\cef.win64\steamwebhelper.exe",
            22272,
            foreground=False,
            selected=True,
            muted=True,
        ),
        app(
            "Phantom Blade Zero",
            "PBZ.exe",
            r"E:\SteamLibrary\steamapps\common\PBZ\platform\steam\PBZ.exe",
            18040,
            foreground=False,
            selected=False,
            muted=False,
        ),
    )


def capture(widget, output: str) -> None:
    widget.update_idletasks()
    widget.update()
    time.sleep(0.35)
    x = widget.winfo_rootx()
    y = widget.winfo_rooty()
    w = widget.winfo_width()
    h = widget.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(output)
    print("saved", output)


def main() -> None:
    set_dpi_awareness()
    data_dir = os.path.join(ROOT, ".data-docs")
    os.makedirs(data_dir, exist_ok=True)
    os.environ["QUIETFOCUS_DATA_DIR"] = data_dir
    os.environ["QUIETFOCUS_NO_TRAY"] = "1"

    app_instance = QuietFocusApp(start_minimized=False)
    app_instance.root.after(1800, lambda: run(app_instance))
    app_instance.run()


def run(app_instance: QuietFocusApp) -> None:
    app_instance._engine.stop()
    apps = sample_apps()
    # Populate the selection state used by the real row widgets.
    app_instance.settings.apps = {
        item.key: {
            "name": item.name,
            "exe_name": item.exe_name,
            "exe_path": item.exe_path,
        }
        for item in apps
        if item.selected
    }
    snapshot = EngineSnapshot(
        apps=apps,
        enabled=True,
        foreground_title="雨爱 - Microsoft Edge",
        foreground_exe="msedge.exe",
        at=time.time(),
        error=None,
        foreground_ready=True,
    )
    app_instance.show_window()
    app_instance._render(snapshot)
    app_instance.root.attributes("-topmost", True)
    app_instance.root.update_idletasks()
    app_instance.root.update()
    time.sleep(0.7)
    capture(app_instance.root, os.path.join(ROOT, "docs", "screenshot.png"))

    app_instance.settings.auto_select_new = True
    import quietfocus.ui.main_window as main_window

    main_window.data_dir = lambda: os.path.join(
        os.environ.get("APPDATA", r"C:\Users\Public"), "QuietFocus"
    )
    app_instance.open_settings()
    app_instance.root.update_idletasks()
    app_instance.root.update()
    time.sleep(0.4)
    dialog = app_instance._settings_window
    if dialog is not None:
        capture(dialog, os.path.join(ROOT, "docs", "settings.png"))
    try:
        app_instance.root.attributes("-topmost", False)
    except Exception:
        pass
    app_instance.root.after(200, app_instance.shutdown)


if __name__ == "__main__":
    main()
