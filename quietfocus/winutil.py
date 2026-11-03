"""Small Windows helpers: version strings, DPI, title bar, autostart, mutex."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import logging
import os
import struct
import sys
from functools import lru_cache

log = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
SHOW_EVENT_NAME = r"Local\QuietFocus.ShowWindow"
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0
GENERIC_DESCRIPTIONS = {
    "microsoft® windows® operating system",
    "windows® operating system",
    "microsoft windows operating system",
    "application",
    "windows",
}


# ----------------------------------------------------------------- DPI / UI
def set_dpi_awareness() -> None:
    """Opt into crisp rendering before Tk creates any window."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(1)
        return
    except Exception:
        pass
    try:
        ctypes.WinDLL("user32").SetProcessDPIAware()
    except Exception:
        pass


def apply_modern_titlebar(hwnd: int) -> None:
    """Give the window a light Windows 11 title bar. Failure is harmless."""
    try:
        user32 = ctypes.WinDLL("user32")
        user32.GetAncestor.argtypes = [w.HWND, ctypes.c_uint]
        user32.GetAncestor.restype = w.HWND
        dwm = ctypes.WinDLL("dwmapi")
        root = user32.GetAncestor(w.HWND(hwnd), 2)  # GA_ROOT
        target = int(root) if root else hwnd
        caption = 0x00F9FAF7  # COLORREF, light warm white
        text = 0x00231F1B
        border = 0x00E8EFEC
        dwm.DwmSetWindowAttribute(w.HWND(target), 35, ctypes.byref(ctypes.c_int(caption)), 4)
        dwm.DwmSetWindowAttribute(w.HWND(target), 36, ctypes.byref(ctypes.c_int(text)), 4)
        dwm.DwmSetWindowAttribute(w.HWND(target), 34, ctypes.byref(ctypes.c_int(border)), 4)
        dwm.DwmSetWindowAttribute(w.HWND(target), 33, ctypes.byref(ctypes.c_int(2)), 4)
    except Exception:
        pass


# ------------------------------------------------------------- file details
@lru_cache(maxsize=512)
def file_description(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    try:
        version = ctypes.WinDLL("version", use_last_error=True)
        version.GetFileVersionInfoSizeW.argtypes = [w.LPCWSTR, ctypes.POINTER(w.DWORD)]
        version.GetFileVersionInfoSizeW.restype = w.DWORD
        version.GetFileVersionInfoW.argtypes = [
            w.LPCWSTR,
            w.DWORD,
            w.DWORD,
            ctypes.c_void_p,
        ]
        version.GetFileVersionInfoW.restype = w.BOOL
        version.VerQueryValueW.argtypes = [
            ctypes.c_void_p,
            w.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(w.UINT),
        ]
        version.VerQueryValueW.restype = w.BOOL

        ignored = w.DWORD()
        size = version.GetFileVersionInfoSizeW(path, ctypes.byref(ignored))
        if not size:
            return ""
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path, 0, size, data):
            return ""

        ptr = ctypes.c_void_p()
        length = w.UINT()
        if not version.VerQueryValueW(
            data, r"\VarFileInfo\Translation", ctypes.byref(ptr), ctypes.byref(length)
        ):
            return ""
        if not length.value or not ptr.value:
            return ""
        lang, codepage = struct.unpack("<HH", ctypes.string_at(ptr.value, 4))
        sub_block = rf"\StringFileInfo\{lang:04x}{codepage:04x}\FileDescription"
        value = ctypes.c_void_p()
        value_len = w.UINT()
        if not version.VerQueryValueW(
            data, sub_block, ctypes.byref(value), ctypes.byref(value_len)
        ):
            return ""
        if not value.value or not value_len.value:
            return ""
        text = ctypes.wstring_at(value.value, value_len.value).strip("\x00").strip()
        if text.casefold() in GENERIC_DESCRIPTIONS:
            return ""
        return text
    except Exception:
        return ""


def open_data_folder(path: str) -> None:
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except OSError as exc:
        log.warning("Could not open %s: %s", path, exc)


# ---------------------------------------------------------------- autostart
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "QuietFocus"


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
    return f'"{pythonw}" "{script}" --minimized'


def get_autostart_command() -> str:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
            return str(value)
    except OSError:
        return ""


def is_autostart_enabled() -> bool:
    return bool(get_autostart_command())


def set_autostart(enabled: bool) -> None:
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass


def refresh_autostart_path() -> None:
    """Keep the Run entry pointing at this executable after an update/move."""
    current = get_autostart_command()
    if not current:
        return
    desired = _startup_command()
    if os.path.normcase(current) != os.path.normcase(desired):
        try:
            set_autostart(True)
        except OSError as exc:
            log.warning("Could not update autostart entry: %s", exc)


# ------------------------------------------------------------ single instance
def acquire_single_instance() -> int | None:
    """Return a mutex handle, or None when another copy is already running."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = w.HANDLE
        handle = kernel32.CreateMutexW(None, False, r"Local\QuietFocus.SingleInstance")
        if not handle:
            return 0
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return None
        return int(handle)
    except Exception:
        return 0


def release_single_instance(handle: int | None) -> None:
    if not handle:
        return
    try:
        ctypes.WinDLL("kernel32").CloseHandle(w.HANDLE(handle))
    except Exception:
        pass


# --------------------------------------------------- show-existing-instance
def create_show_event() -> int | None:
    """Create the auto-reset event used to ask the running copy to show."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateEventW.argtypes = [
            ctypes.c_void_p,
            w.BOOL,
            w.BOOL,
            w.LPCWSTR,
        ]
        kernel32.CreateEventW.restype = w.HANDLE
        handle = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        return int(handle) if handle else None
    except Exception:
        return None


def signal_show_existing() -> bool:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenEventW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
        kernel32.OpenEventW.restype = w.HANDLE
        kernel32.SetEvent.argtypes = [w.HANDLE]
        kernel32.SetEvent.restype = w.BOOL
        kernel32.CloseHandle.argtypes = [w.HANDLE]
        handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
        if not handle:
            return False
        try:
            return bool(kernel32.SetEvent(handle))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def wait_for_show_event(handle: int | None, timeout_ms: int = 500) -> bool:
    if not handle:
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        kernel32.WaitForSingleObject.restype = w.DWORD
        return kernel32.WaitForSingleObject(w.HANDLE(handle), timeout_ms) == WAIT_OBJECT_0
    except Exception:
        return False


def close_show_event(handle: int | None) -> None:
    if not handle:
        return
    try:
        ctypes.WinDLL("kernel32").CloseHandle(w.HANDLE(handle))
    except Exception:
        pass


def message_box(text: str, title: str = "静界 QuietFocus", error: bool = False) -> None:
    try:
        flags = 0x10 if error else 0x40
        ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    except Exception:
        pass


def flash_window(hwnd: int) -> None:
    try:
        ctypes.windll.user32.FlashWindow(w.HWND(hwnd), True)
    except Exception:
        pass
