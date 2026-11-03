"""Live test: tray shell surfaces must not count as an app foreground change."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import os
import sys
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import comtypes  # noqa: E402
import psutil  # noqa: E402
import winsound  # noqa: E402
from pycaw.pycaw import AudioUtilities  # noqa: E402

from quietfocus.audio import AudioController  # noqa: E402
from quietfocus.foreground import get_foreground_context  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetForegroundWindow.argtypes = [w.HWND]
user32.GetForegroundWindow.restype = w.HWND
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user32.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
user32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
user32.IsWindowVisible.argtypes = [w.HWND]
user32.IsWindowVisible.restype = w.BOOL
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.FindWindowW.argtypes = [w.LPCWSTR, w.LPCWSTR]
user32.FindWindowW.restype = w.HWND

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def force_foreground(hwnd: int) -> bool:
    current = user32.GetForegroundWindow()
    current_pid = w.DWORD()
    target_pid = w.DWORD()
    current_tid = user32.GetWindowThreadProcessId(current, ctypes.byref(current_pid))
    target_tid = user32.GetWindowThreadProcessId(w.HWND(hwnd), ctypes.byref(target_pid))
    user32.AttachThreadInput(current_tid, target_tid, True)
    try:
        user32.ShowWindow(w.HWND(hwnd), 9)
        ok = bool(user32.SetForegroundWindow(w.HWND(hwnd)))
    finally:
        user32.AttachThreadInput(current_tid, target_tid, False)
    time.sleep(0.4)
    return ok and int(user32.GetForegroundWindow() or 0) == hwnd


def find_window(contains: str = "") -> int:
    found = []
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user32.EnumWindows.restype = w.BOOL

    @callback_type
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if contains.casefold() in buffer.value.casefold():
            found.append((hwnd, buffer.value))
        return True

    user32.EnumWindows(callback, 0)
    return int(found[0][0]) if found else 0


def session_for_pid(pid: int):
    for session in AudioUtilities.GetAllSessions():
        if session.ProcessId == pid:
            return session
    return None


def edge_sessions():
    return [
        session
        for session in AudioUtilities.GetAllSessions()
        if session.Process and session.Process.name() == "msedge.exe"
    ]


def main() -> int:
    edge_hwnd = find_window("bilibili") or find_window("edge")
    tray_hwnd = user32.FindWindowW("Shell_TrayWnd", None)
    sessions = edge_sessions()
    if not sessions or not edge_hwnd or not tray_hwnd:
        print("SKIP: could not find an Edge window and the taskbar")
        return 0
    edge_exe = sessions[0].Process.exe()

    data_dir = os.path.join(ROOT, ".data-foreground")
    os.makedirs(data_dir, exist_ok=True)
    os.environ["QUIETFOCUS_DATA_DIR"] = data_dir
    silent = os.path.join(data_dir, "silence.wav")
    if not os.path.exists(silent):
        with wave.open(silent, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(b"\x00\x00" * 44100)
    winsound.PlaySound(
        silent, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP
    )
    time.sleep(0.5)

    self_pid = os.getpid()
    self_exe = psutil.Process(self_pid).exe()
    edge_key = "path:" + os.path.normcase(os.path.normpath(edge_exe))
    self_key = "path:" + os.path.normcase(os.path.normpath(self_exe))
    selected = {edge_key, self_key}

    comtypes.CoInitialize()
    failures = []
    controller = AudioController(
        get_selected=lambda: set(selected),
        get_enabled=lambda: True,
        get_interval=lambda: 0.8,
        on_snapshot=lambda _snapshot: None,
        foreground_provider=get_foreground_context,
    )
    try:
        if not force_foreground(edge_hwnd):
            print("SKIP: Windows refused to switch focus to Edge")
            return 0
        snapshot = controller.scan_once()
        edge_muted = any(s.SimpleAudioVolume.GetMute() for s in edge_sessions())
        self_muted = bool(session_for_pid(self_pid).SimpleAudioVolume.GetMute())
        print(
            "edge foreground -> edge muted:",
            edge_muted,
            "helper muted:",
            self_muted,
            "ready:",
            snapshot.foreground_ready,
        )
        if edge_muted:
            failures.append("Edge was muted while foreground")
        if not self_muted:
            failures.append("background helper was not muted")

        if force_foreground(tray_hwnd):
            time.sleep(0.4)
            snapshot = controller.scan_once()
            edge_muted = any(s.SimpleAudioVolume.GetMute() for s in edge_sessions())
            self_muted = bool(session_for_pid(self_pid).SimpleAudioVolume.GetMute())
            print(
                "tray surface -> edge muted:",
                edge_muted,
                "helper muted:",
                self_muted,
                "ready:",
                snapshot.foreground_ready,
            )
            if edge_muted:
                failures.append("Opening the taskbar/overflow muted the previous app")
        else:
            print("SKIP: Windows refused to focus the taskbar")
    finally:
        controller._restore_all()
        winsound.PlaySound(None, winsound.SND_PURGE)
        if edge_hwnd:
            force_foreground(edge_hwnd)
        comtypes.CoUninitialize()

    if failures:
        print("FAIL:", "; ".join(failures))
        return 1
    print("PASS: foreground app survived tray-shell focus")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
