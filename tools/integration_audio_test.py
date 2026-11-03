"""Live Core Audio integration test using a silent looping WAV."""

from __future__ import annotations

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
from quietfocus.foreground import ForegroundContext  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _session_for_pid(pid: int):
    for session in AudioUtilities.GetAllSessions():
        if session.ProcessId == pid:
            return session
    return None


def main() -> int:
    data_dir = os.path.join(ROOT, ".data-integration")
    os.makedirs(data_dir, exist_ok=True)
    os.environ["QUIETFOCUS_DATA_DIR"] = data_dir
    silent = os.path.join(data_dir, "silence.wav")
    if not os.path.exists(silent):
        with wave.open(silent, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(b"\x00\x00" * 44100)

    comtypes.CoInitialize()
    winsound.PlaySound(
        silent, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP
    )
    pid = os.getpid()
    session = None
    for _ in range(30):
        session = _session_for_pid(pid)
        if session is not None:
            break
        time.sleep(0.15)
    if session is None:
        print("FAIL: no audio session was created")
        winsound.PlaySound(None, winsound.SND_PURGE)
        return 1

    exe = psutil.Process(pid).exe()
    key = "path:" + os.path.normcase(os.path.normpath(exe))
    selected = {key}
    enabled = True
    other_pid = next(
        (value for value in psutil.pids() if value not in (0, pid)), 0
    )
    fake = {
        "ctx": ForegroundContext(
            hwnd=1,
            pid=other_pid,
            exe_path=r"C:\Other\Other.exe",
            exe_name="Other.exe",
            title="Other",
            window_pids=frozenset({other_pid}),
        )
    }

    def foreground():
        return fake["ctx"]

    controller = AudioController(
        get_selected=lambda: set(selected),
        get_enabled=lambda: enabled,
        get_interval=lambda: 0.8,
        on_snapshot=lambda _snapshot: None,
        foreground_provider=foreground,
    )
    failures = []
    try:
        controller.scan_once()
        current = _session_for_pid(pid)
        muted_background = bool(current.SimpleAudioVolume.GetMute()) if current else None
        print("background mute:", muted_background)
        if not muted_background:
            failures.append("session was not muted in background")

        fake["ctx"] = ForegroundContext(
            hwnd=2,
            pid=pid,
            exe_path=exe,
            exe_name=os.path.basename(exe),
            title="Target",
            window_pids=frozenset({pid}),
        )
        controller.scan_once()
        current = _session_for_pid(pid)
        muted_foreground = bool(current.SimpleAudioVolume.GetMute()) if current else None
        print("foreground mute:", muted_foreground)
        if muted_foreground:
            failures.append("session was not unmuted in foreground")

        selected.clear()
        controller.scan_once()
        current = _session_for_pid(pid)
        muted_released = bool(current.SimpleAudioVolume.GetMute()) if current else None
        print("released mute:", muted_released)
        if muted_released:
            failures.append("session was not restored after deselect")

        # Now verify the real worker lifecycle: start, mute in background, stop
        # and restore. This is what happens when the window is closed.
        fake["ctx"] = ForegroundContext(
            hwnd=1,
            pid=other_pid,
            exe_path=r"C:\Other\Other.exe",
            exe_name="Other.exe",
            title="Other",
            window_pids=frozenset({other_pid}),
        )
        selected.add(key)
        worker = AudioController(
            get_selected=lambda: set(selected),
            get_enabled=lambda: enabled,
            get_interval=lambda: 0.3,
            on_snapshot=lambda _snapshot: None,
            foreground_provider=foreground,
        )
        worker.start()
        try:
            muted_by_worker = False
            for _ in range(20):
                time.sleep(0.15)
                current = _session_for_pid(pid)
                if current and current.SimpleAudioVolume.GetMute():
                    muted_by_worker = True
                    break
            print("worker muted:", muted_by_worker)
            if not muted_by_worker:
                failures.append("worker did not mute the background session")
        finally:
            worker.stop()
        time.sleep(0.2)
        current = _session_for_pid(pid)
        muted_after_stop = bool(current.SimpleAudioVolume.GetMute()) if current else None
        print("mute after worker stop:", muted_after_stop)
        if muted_after_stop:
            failures.append("worker did not restore the session on stop")
        journal = os.path.join(data_dir, "restore.json")
        if os.path.exists(journal):
            failures.append("restore journal was not cleared after graceful stop")
    finally:
        controller._restore_all()
        winsound.PlaySound(None, winsound.SND_PURGE)
        comtypes.CoUninitialize()

    if failures:
        print("FAIL:", "; ".join(failures))
        return 1
    print("PASS: discovered session, muted in background, unmuted in foreground, restored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
