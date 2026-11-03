"""Capture a top-level window by title (DPI-aware). Developer utility."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import sys
import time

from PIL import ImageGrab

sys.path.insert(0, ".")
from quietfocus.winutil import set_dpi_awareness

ENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.EnumWindows.argtypes = [ENUMPROC, w.LPARAM]
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
user32.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = w.BOOL
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]


def find_window(needle: str):
    found = []

    @ENUMPROC
    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if needle.casefold() in buf.value.casefold():
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(callback, 0)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    set_dpi_awareness()
    windows = find_window(args.title)
    if not windows:
        print("window not found")
        return 1
    hwnd, title = windows[0]
    user32.ShowWindow(hwnd, 9)
    user32.SetWindowPos(hwnd, w.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)
    time.sleep(0.6)
    rect = w.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(args.out)
    user32.SetWindowPos(hwnd, w.HWND(-2), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    print("saved", args.out, (right - left, bottom - top), title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
