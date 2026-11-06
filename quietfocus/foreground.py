"""Foreground-window detection with basic UWP/ApplicationFrameHost support."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import logging
import os
from dataclasses import dataclass, field
from typing import Iterable

import psutil

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetForegroundWindow.restype = w.HWND
_user32.IsWindow.argtypes = [w.HWND]
_user32.IsWindow.restype = w.BOOL
_user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
_user32.GetWindowThreadProcessId.restype = w.DWORD
_user32.GetWindowTextLengthW.argtypes = [w.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetAncestor.argtypes = [w.HWND, ctypes.c_uint]
_user32.GetAncestor.restype = w.HWND

_ENUM_PROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
_user32.EnumChildWindows.argtypes = [w.HWND, _ENUM_PROC, w.LPARAM]
_user32.EnumChildWindows.restype = w.BOOL


# Shell/tray surfaces are not content applications. Opening the hidden-icon
# overflow or the Start menu must not make the current app look "background".
_TRANSIENT_CLASSES = {
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow",
    "TopLevelWindowForOverflowXamlIsland",
    "XamlExplorerHostIslandWindow",
}
_SHELL_PROCESSES = {
    # Quick settings / volume / network flyouts are transient overlays.
    "explorer.exe",
    "shellexperiencehost.exe",
    # The IME candidate window should not count as leaving the app.
    "textinputhost.exe",
    "lockapp.exe",
}
# StartMenuExperienceHost.exe and SearchHost.exe are intentionally NOT in this
# set: opening the Start menu or search means the previous app is no longer
# foreground and should be muted.


@dataclass(frozen=True)
class ForegroundContext:
    hwnd: int
    pid: int
    exe_path: str
    exe_name: str
    title: str
    window_pids: frozenset[int] = field(default_factory=frozenset)
    ancestor_pids: frozenset[int] = field(default_factory=frozenset)
    root_pid: int = 0
    class_name: str = ""
    is_transient: bool = False
    is_own: bool = False


def _safe_process(pid: int) -> tuple[str, str]:
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        try:
            path = proc.exe()
        except (psutil.AccessDenied, OSError):
            path = ""
        return name or "", path or ""
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return "", ""


def _window_text(hwnd: int) -> str:
    try:
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value.strip()
    except Exception:
        return ""


def _window_class(hwnd: int) -> str:
    try:
        buffer = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, buffer, 256)
        return buffer.value
    except Exception:
        return ""


def _is_transient_surface(class_name: str, exe_name: str) -> bool:
    if class_name in _TRANSIENT_CLASSES:
        return True
    # Start/Search/IME surfaces use the generic CoreWindow class on Windows 10.
    if class_name == "Windows.UI.Core.CoreWindow":
        return exe_name.casefold() in _SHELL_PROCESSES
    return False


def _collect_child_pids(hwnd: int) -> set[int]:
    pids: set[int] = set()

    @_ENUM_PROC
    def callback(child: int, _lparam: int) -> bool:
        pid = w.DWORD()
        _user32.GetWindowThreadProcessId(child, ctypes.byref(pid))
        if pid.value:
            pids.add(int(pid.value))
        return True

    try:
        _user32.EnumChildWindows(w.HWND(hwnd), callback, 0)
    except Exception:
        pass
    return pids


def _ancestors(pid: int, limit: int = 8) -> list[int]:
    result: list[int] = []
    try:
        proc = psutil.Process(pid)
        for _ in range(limit):
            parent = proc.parent()
            if parent is None:
                break
            result.append(parent.pid)
            proc = parent
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        pass
    return result


def get_foreground_context() -> ForegroundContext | None:
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd or not _user32.IsWindow(hwnd):
            return None
        pid = w.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        name, path = _safe_process(pid.value)
        if not name:
            return None
        ancestors = _ancestors(pid.value)
        window_pids = _collect_child_pids(hwnd)
        window_pids.add(int(pid.value))
        class_name = _window_class(hwnd)
        return ForegroundContext(
            hwnd=int(hwnd),
            pid=int(pid.value),
            exe_path=path,
            exe_name=name,
            title=_window_text(hwnd),
            window_pids=frozenset(window_pids),
            ancestor_pids=frozenset(ancestors),
            root_pid=ancestors[-1] if ancestors else int(pid.value),
            class_name=class_name,
            is_transient=_is_transient_surface(class_name, name),
            is_own=int(pid.value) == os.getpid(),
        )
    except Exception as exc:
        log.debug("Foreground lookup failed: %s", exc)
        return None


def _same_path(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(
        os.path.normpath(b)
    )


def _is_ancestor(ancestor: int, pid: int, limit: int = 5) -> bool:
    try:
        proc = psutil.Process(pid)
        for _ in range(limit):
            parent = proc.parent()
            if parent is None:
                return False
            if parent.pid == ancestor:
                return True
            proc = parent
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False
    return False


def _normalized_name(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def is_session_foreground(
    pid: int,
    exe_path: str,
    exe_name: str,
    display_name: str,
    fg: ForegroundContext | None,
) -> bool:
    """Decide whether an audio session belongs to the foreground application."""
    if fg is None or not pid:
        return False
    if pid in fg.window_pids:
        return True
    if _same_path(exe_path, fg.exe_path):
        return True

    # Chromium/Electron and games often put the window in one process and the
    # audio session in a sibling process with the same executable name.
    if exe_name and fg.exe_name and exe_name.casefold() == fg.exe_name.casefold():
        if pid in fg.ancestor_pids or fg.pid in _ancestors(pid, 4):
            return True

    # A helper process (different executable) owned by the foreground app.
    if fg.pid in _ancestors(pid, 3):
        return True

    # UWP apps: the frame belongs to ApplicationFrameHost while the audio
    # session belongs to the packaged app. Child-window PIDs normally cover
    # this, but the display-name fallback catches windows without child HWNDs.
    if fg.exe_name.casefold() == "applicationframehost.exe" and display_name:
        dn = _normalized_name(display_name)
        title = _normalized_name(fg.title)
        if dn and len(dn) >= 3 and (dn in title or title in dn):
            return True

    return False


def any_pids_foreground(pids: Iterable[int], fg: ForegroundContext | None) -> bool:
    return bool(fg and set(pids) & fg.window_pids)
