"""Unit tests for the mute/restore state machine (no real audio device needed)."""

from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

from quietfocus.audio import AudioController
from quietfocus.foreground import ForegroundContext

EXE = r"C:\Fake\Music.exe"
KEY = "path:" + os.path.normcase(EXE)


class FakeVolume:
    def __init__(self, muted: bool = False) -> None:
        self.muted = muted

    def GetMute(self) -> int:
        return int(self.muted)

    def SetMute(self, value, _context=None) -> None:
        self.muted = bool(value)

    def GetMasterVolume(self) -> float:
        return 1.0


class FakeSession:
    def __init__(self, sid: str, pid: int, muted: bool = False) -> None:
        self.ProcessId = pid
        self.State = 1
        self.SimpleAudioVolume = FakeVolume(muted)
        self.DisplayName = "Music"
        self.InstanceIdentifier = sid
        self.Identifier = sid


class FakeForeground:
    def __init__(
        self,
        pid: int,
        path: str,
        name: str,
        *,
        transient: bool = False,
        own: bool = False,
    ) -> None:
        self.ctx = ForegroundContext(
            hwnd=1,
            pid=pid,
            exe_path=path,
            exe_name=name,
            title="Test",
            window_pids=frozenset({pid}),
            class_name="Shell_TrayWnd" if transient else "TestWindow",
            is_transient=transient,
            is_own=own,
        )

    def __call__(self):
        return self.ctx


class AudioControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        temp_root = root / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        # Cleanup is deliberately skipped: the DSH workspace ACL denies
        # recursive deletion under a restricted process. Plain os.makedirs is
        # important here; tempfile.mkdtemp creates a restrictive DACL that the
        # sandbox then refuses writes inside.
        self.temp_path = os.path.join(
            temp_root, f"run-{os.getpid()}-{uuid.uuid4().hex}"
        )
        os.makedirs(self.temp_path)
        self.env = mock.patch.dict(
            os.environ, {"QUIETFOCUS_DATA_DIR": self.temp_path}
        )
        self.env.start()
        self.processes = {
            100: ("Music.exe", EXE),
            200: ("Other.exe", r"C:\Fake\Other.exe"),
        }
        self.patch_proc = mock.patch(
            "quietfocus.audio._ProcessCache.get",
            lambda cache, pid: self.processes.get(pid, ("", "")),
        )
        self.patch_proc.start()
        self.patch_pid = mock.patch(
            "quietfocus.audio.psutil.pid_exists", return_value=True
        )
        self.patch_pid.start()

        self.selected: set[str] = {KEY}
        self.enabled = True
        self.session = FakeSession("session-1", 100)
        self.foreground = FakeForeground(200, r"C:\Fake\Other.exe", "Other.exe")
        self.snapshot = None
        self.controller = None

    def tearDown(self) -> None:
        if self.controller is not None:
            self.controller._restore_all()
        self.patch_pid.stop()
        self.patch_proc.stop()
        self.env.stop()

    def make(self, sessions, foreground=None):
        self.controller = AudioController(
            get_selected=lambda: set(self.selected),
            get_enabled=lambda: self.enabled,
            get_interval=lambda: 0.8,
            on_snapshot=lambda snap: setattr(self, "snapshot", snap),
            session_provider=lambda: list(sessions),
            foreground_provider=lambda: (foreground or self.foreground)(),
        )
        return self.controller

    def test_mutes_background_and_unmutes_foreground(self):
        self.make([self.session])
        snapshot = self.controller.scan_once()
        self.assertTrue(self.session.SimpleAudioVolume.muted)
        self.assertTrue(snapshot.apps[0].controlled)
        self.assertFalse(snapshot.apps[0].is_foreground)

        self.foreground = FakeForeground(100, EXE, "Music.exe")
        snapshot = self.controller.scan_once()
        self.assertFalse(self.session.SimpleAudioVolume.muted)
        self.assertTrue(snapshot.apps[0].is_foreground)

    def test_unselected_app_is_not_touched(self):
        self.session.SimpleAudioVolume.muted = True
        self.selected.clear()
        self.make([self.session])
        self.controller.scan_once()
        self.assertTrue(self.session.SimpleAudioVolume.muted)

    def test_deselect_restores_original_mute(self):
        self.make([self.session])
        self.controller.scan_once()
        self.assertTrue(self.session.SimpleAudioVolume.muted)
        self.selected.clear()
        self.controller.scan_once()
        self.assertFalse(self.session.SimpleAudioVolume.muted)

    def test_disable_restores_original_mute(self):
        self.make([self.session])
        self.controller.scan_once()
        self.enabled = False
        self.controller.scan_once()
        self.assertFalse(self.session.SimpleAudioVolume.muted)

    def test_existing_mute_is_restored_when_released(self):
        self.session.SimpleAudioVolume.muted = True
        self.make([self.session])
        self.foreground = FakeForeground(100, EXE, "Music.exe")
        self.controller.scan_once()
        self.assertFalse(self.session.SimpleAudioVolume.muted)
        self.selected.clear()
        self.controller.scan_once()
        self.assertTrue(self.session.SimpleAudioVolume.muted)

    def test_journal_recovers_after_forced_exit(self):
        self.make([self.session])
        self.controller.scan_once()
        self.assertTrue(self.session.SimpleAudioVolume.muted)
        journal = os.path.join(self.temp_path, "restore.json")
        self.assertTrue(os.path.exists(journal))

        # Simulate a new process after a crash. The old controller must not
        # restore anything.
        self.controller = None
        self.session.SimpleAudioVolume.muted = True
        recovered = self.make([self.session])
        recovered._recover_from_journal()
        self.assertFalse(self.session.SimpleAudioVolume.muted)
        self.assertFalse(os.path.exists(journal))

    def test_graceful_restore_clears_journal(self):
        self.make([self.session])
        self.controller.scan_once()
        self.controller._restore_all()
        self.assertFalse(self.session.SimpleAudioVolume.muted)
        self.assertFalse(os.path.exists(os.path.join(self.temp_path, "restore.json")))

    def test_transient_shell_surface_does_not_mute(self):
        # Opening the tray overflow must not make the current app background.
        self.foreground = FakeForeground(
            300, r"C:\Windows\explorer.exe", "explorer.exe", transient=True
        )
        self.make([self.session])
        snapshot = self.controller.scan_once()
        self.assertFalse(snapshot.foreground_ready)
        self.assertFalse(self.session.SimpleAudioVolume.muted)

        # Once a real foreground is known, a transient tray window keeps it.
        self.foreground = FakeForeground(100, EXE, "Music.exe")
        self.controller.scan_once()
        self.assertFalse(self.session.SimpleAudioVolume.muted)
        self.foreground = FakeForeground(
            300, r"C:\Windows\explorer.exe", "explorer.exe", transient=True
        )
        snapshot = self.controller.scan_once()
        self.assertTrue(snapshot.foreground_ready)
        self.assertFalse(self.session.SimpleAudioVolume.muted)

    def test_own_window_does_not_mute_previous_app(self):
        self.foreground = FakeForeground(100, EXE, "Music.exe")
        self.make([self.session])
        self.controller.scan_once()
        self.assertFalse(self.session.SimpleAudioVolume.muted)

        self.foreground = FakeForeground(
            999, r"C:\QuietFocus\QuietFocus.exe", "QuietFocus.exe", own=True
        )
        snapshot = self.controller.scan_once()
        self.assertTrue(snapshot.foreground_ready)
        self.assertFalse(self.session.SimpleAudioVolume.muted)
        self.assertTrue(snapshot.apps[0].controlled)

    def test_waits_for_real_foreground_at_startup(self):
        self.foreground = FakeForeground(
            999, r"C:\QuietFocus\QuietFocus.exe", "QuietFocus.exe", own=True
        )
        self.make([self.session])
        snapshot = self.controller.scan_once()
        self.assertFalse(snapshot.foreground_ready)
        self.assertFalse(self.session.SimpleAudioVolume.muted)
        self.assertTrue(snapshot.apps[0].selected)
        self.assertFalse(snapshot.apps[0].controlled)


if __name__ == "__main__":
    unittest.main()
