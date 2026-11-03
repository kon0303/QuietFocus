"""Windows Core Audio session discovery and automatic mute control."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

import comtypes
import psutil
from pycaw.pycaw import AudioUtilities

from .foreground import (
    ForegroundContext,
    get_foreground_context,
    is_session_foreground,
)
from .paths import restore_journal_path
from .recovery import RestoreJournal
from .winutil import file_description

log = logging.getLogger(__name__)

# Windows AudioSessionState values.
STATE_INACTIVE = 0
STATE_ACTIVE = 1
STATE_EXPIRED = 2

GENERIC_NAMES = {
    "microsoft® windows® operating system",
    "windows® operating system",
    "application",
    "windows",
}


@dataclass(frozen=True)
class AppSnapshot:
    key: str
    name: str
    exe_name: str
    exe_path: str
    pids: tuple[int, ...]
    session_count: int
    is_foreground: bool
    selected: bool
    controlled: bool
    muted: bool
    active: bool


@dataclass(frozen=True)
class EngineSnapshot:
    apps: tuple[AppSnapshot, ...]
    enabled: bool
    foreground_title: str
    foreground_exe: str
    at: float
    error: str | None = None
    foreground_ready: bool = False


@dataclass
class _LiveSession:
    sid: str
    pid: int
    muted: bool
    volume: float
    active: bool
    display_name: str
    raw_volume: object


@dataclass
class _Group:
    key: str
    name: str
    exe_name: str
    exe_path: str
    pids: set[int] = field(default_factory=set)
    sessions: list[_LiveSession] = field(default_factory=list)
    is_foreground: bool = False


def _clean_display_name(value: str) -> str:
    if not value:
        return ""
    value = value.strip()
    if not value or value.startswith("@") or ".dll,-" in value.casefold():
        return ""
    if value.casefold() in GENERIC_NAMES:
        return ""
    return value


def _friendly_name(display: str, exe_path: str, exe_name: str) -> str:
    display = _clean_display_name(display)
    if display:
        return display
    description = file_description(exe_path)
    if description:
        return description
    stem = os.path.splitext(exe_name)[0].strip()
    if stem:
        return stem.replace("_", " ").replace("-", " ").strip()
    return "未知应用"


def _app_key(exe_path: str, exe_name: str, display: str) -> str:
    # UWP applications are often hosted by the shared ApplicationFrameHost
    # executable. Group them by their display name instead of collapsing every
    # UWP app into one row.
    if exe_name.casefold() == "applicationframehost.exe" and display:
        return "uwp:" + display.casefold()
    if exe_path:
        return "path:" + os.path.normcase(os.path.normpath(exe_path))
    if exe_name:
        return "exe:" + exe_name.casefold()
    return "name:" + display.casefold()


class _ProcessCache:
    def __init__(self) -> None:
        self._cache: dict[int, tuple[str, str]] = {}

    def get(self, pid: int) -> tuple[str, str]:
        if pid in self._cache:
            return self._cache[pid]
        try:
            process = psutil.Process(pid)
            name = process.name() or ""
            try:
                path = process.exe() or ""
            except (psutil.AccessDenied, OSError):
                path = ""
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            name, path = "", ""
        self._cache[pid] = (name, path)
        return name, path


class AudioController:
    """Background scanner that mutes controlled apps when they are not foreground.

    ``session_provider`` and ``foreground_provider`` can be replaced in tests.
    All COM work happens on the worker thread; callbacks must be thread-safe.
    """

    def __init__(
        self,
        get_selected: Callable[[], set[str]],
        get_enabled: Callable[[], bool],
        get_interval: Callable[[], float],
        on_snapshot: Callable[[EngineSnapshot], None],
        session_provider: Callable[[], Sequence[object]] = AudioUtilities.GetAllSessions,
        foreground_provider: Callable[[], ForegroundContext | None] = get_foreground_context,
    ) -> None:
        self._get_selected = get_selected
        self._get_enabled = get_enabled
        self._get_interval = get_interval
        self._on_snapshot = on_snapshot
        self._session_provider = session_provider
        self._foreground_provider = foreground_provider

        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._baseline: dict[str, bool] = {}
        self._last_error: str | None = None
        self._lock = threading.Lock()
        self._journal = RestoreJournal(restore_journal_path())
        self._effective_fg: ForegroundContext | None = None
        self._foreground_ready = False

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="QuietFocusAudio", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 6.0) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop.set()
        self._wake.set()
        thread.join(timeout)
        if thread.is_alive():
            log.warning("Audio worker did not stop within %.1fs", timeout)
        self._thread = None

    def wake(self) -> None:
        self._wake.set()

    @property
    def touched_sessions(self) -> int:
        with self._lock:
            return len(self._baseline)

    # --------------------------------------------------------------- worker
    def _run(self) -> None:
        comtypes.CoInitialize()
        try:
            self._recover_from_journal()
            while not self._stop.is_set():
                self._wake.clear()
                started = time.monotonic()
                try:
                    snapshot = self.scan_once()
                except Exception as exc:
                    message = self._describe_error(exc)
                    if message != self._last_error:
                        log.exception("Audio scan failed")
                        self._last_error = message
                    snapshot = EngineSnapshot(
                        apps=(),
                        enabled=bool(self._get_enabled()),
                        foreground_title="",
                        foreground_exe="",
                        at=time.time(),
                        error=message,
                    )
                    self._emit(snapshot)
                else:
                    if self._last_error is not None:
                        log.info("Audio scanning recovered")
                    self._last_error = None
                    self._emit(snapshot)

                try:
                    interval = float(self._get_interval())
                except Exception:
                    interval = 0.8
                elapsed = time.monotonic() - started
                delay = max(0.12, min(5.0, interval) - elapsed)
                self._wake.wait(delay)
        finally:
            try:
                self._restore_all()
            finally:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    def _emit(self, snapshot: EngineSnapshot) -> None:
        try:
            self._on_snapshot(snapshot)
        except Exception:
            log.exception("Snapshot callback failed")

    @staticmethod
    def _describe_error(exc: Exception) -> str:
        text = str(exc).strip()
        if not text:
            text = exc.__class__.__name__
        if len(text) > 160:
            text = text[:157] + "..."
        return f"无法读取音频会话：{text}"

    # -------------------------------------------------------------- scanning
    def scan_once(self) -> EngineSnapshot:
        current_fg = self._foreground_provider()
        # Ignore our own settings window and shell/tray flyouts: opening the
        # hidden-icon overflow or this window must not silence the app the user
        # was actually using.
        if (
            current_fg is not None
            and not current_fg.is_transient
            and not current_fg.is_own
        ):
            self._effective_fg = current_fg
            self._foreground_ready = True

        fg = self._effective_fg
        if fg is not None:
            try:
                if not psutil.pid_exists(fg.pid):
                    fg = None
                    self._effective_fg = None
                    self._foreground_ready = False
            except Exception:
                pass

        raw_sessions = list(self._session_provider())
        selected = set(self._get_selected())
        enabled = bool(self._get_enabled())
        ready = self._foreground_ready and fg is not None
        now = time.time()

        groups: dict[str, _Group] = {}
        seen_sessions: set[str] = set()
        proc_cache = _ProcessCache()

        for raw in raw_sessions:
            try:
                pid = int(raw.ProcessId)
            except Exception:
                continue
            if pid <= 0:
                continue  # "System Sounds" has no owning application

            try:
                state = int(raw.State)
                if state == STATE_EXPIRED:
                    continue
                audio_volume = raw.SimpleAudioVolume
                muted = bool(audio_volume.GetMute())
                volume = float(audio_volume.GetMasterVolume())
            except Exception as exc:
                log.debug("Skipping unreadable session pid=%s: %s", pid, exc)
                continue

            try:
                display = _clean_display_name(raw.DisplayName or "")
            except Exception:
                display = ""
            try:
                instance = raw.InstanceIdentifier or ""
            except Exception:
                instance = ""
            sid = instance or f"{pid}:{getattr(raw, 'Identifier', '')}"
            if sid in seen_sessions:
                continue
            seen_sessions.add(sid)

            exe_name, exe_path = proc_cache.get(pid)
            key = _app_key(exe_path, exe_name, display)
            group = groups.get(key)
            if group is None:
                group = _Group(
                    key=key,
                    name=_friendly_name(display, exe_path, exe_name),
                    exe_name=exe_name,
                    exe_path=exe_path,
                )
                groups[key] = group
            if not group.exe_path and exe_path:
                group.exe_path = exe_path
            if not group.exe_name and exe_name:
                group.exe_name = exe_name
            if group.name == "未知应用" and display:
                group.name = _friendly_name(display, exe_path, exe_name)

            group.pids.add(pid)
            group.sessions.append(
                _LiveSession(
                    sid=sid,
                    pid=pid,
                    muted=muted,
                    volume=volume,
                    active=state == STATE_ACTIVE,
                    display_name=display,
                    raw_volume=audio_volume,
                )
            )

        controlled_keys: set[str] = set()
        for key, group in groups.items():
            group.is_foreground = any(
                is_session_foreground(
                    session.pid,
                    group.exe_path,
                    group.exe_name,
                    session.display_name,
                    fg,
                )
                for session in group.sessions
            )
            if key in selected and enabled and ready:
                controlled_keys.add(key)
                self._control_group(group)
            else:
                self._release_group(group)

        pruned = False
        with self._lock:
            for sid in list(self._baseline):
                if sid not in seen_sessions:
                    # The session ended while muted; there is no longer an
                    # object to restore. A recreated session starts unmuted.
                    self._baseline.pop(sid, None)
                    pruned = True
        if pruned:
            self._persist_journal()

        apps = []
        for key, group in groups.items():
            is_controlled = key in controlled_keys
            muted = any(session.muted for session in group.sessions)
            apps.append(
                AppSnapshot(
                    key=key,
                    name=group.name,
                    exe_name=group.exe_name,
                    exe_path=group.exe_path,
                    pids=tuple(sorted(group.pids)),
                    session_count=len(group.sessions),
                    is_foreground=group.is_foreground,
                    selected=key in selected,
                    controlled=is_controlled,
                    muted=muted,
                    active=any(session.active for session in group.sessions),
                )
            )

        apps.sort(key=lambda app: (app.name.casefold(), app.exe_name.casefold()))
        return EngineSnapshot(
            apps=tuple(apps),
            enabled=enabled,
            foreground_title=fg.title if fg else "",
            foreground_exe=fg.exe_name if fg else "",
            at=now,
            error=None,
            foreground_ready=ready,
        )

    def _control_group(self, group: _Group) -> None:
        target_muted = not group.is_foreground
        added = False
        with self._lock:
            for session in group.sessions:
                if session.sid not in self._baseline:
                    self._baseline[session.sid] = session.muted
                    added = True
        if added:
            # Persist before changing any mute state, so a crash between these
            # two points can still be recovered on the next launch.
            self._persist_journal()
        for session in group.sessions:
            if session.muted == target_muted:
                continue
            if self._set_mute(session, target_muted):
                log.debug(
                    "%s session %s -> %s",
                    group.name,
                    session.pid,
                    "muted" if target_muted else "unmuted",
                )

    def _release_group(self, group: _Group) -> None:
        changed = False
        for session in group.sessions:
            with self._lock:
                if session.sid not in self._baseline:
                    continue
                baseline = self._baseline[session.sid]
            if session.muted != baseline:
                if self._set_mute(session, baseline):
                    log.debug(
                        "%s session %s restored to %s",
                        group.name,
                        session.pid,
                        "muted" if baseline else "unmuted",
                    )
                else:
                    continue
            with self._lock:
                self._baseline.pop(session.sid, None)
            changed = True
        if changed:
            self._persist_journal()

    def _persist_journal(self) -> None:
        with self._lock:
            snapshot = dict(self._baseline)
        self._journal.save(snapshot)

    def _set_mute(self, session: _LiveSession, muted: bool) -> bool:
        try:
            session.raw_volume.SetMute(1 if muted else 0, None)  # type: ignore[attr-defined]
            session.muted = muted
            return True
        except Exception as exc:
            log.warning("Could not change mute for pid %s: %s", session.pid, exc)
            return False

    # --------------------------------------------------------------- restore
    def _recover_from_journal(self) -> None:
        """Undo mutes left behind by a previous crash or forced kill."""
        baseline = self._journal.load()
        if not baseline:
            return
        log.info("Found %d sessions in the restore journal", len(baseline))
        try:
            raw_sessions = list(self._session_provider())
        except Exception as exc:
            log.warning("Could not apply restore journal: %s", exc)
            return
        remaining = dict(baseline)
        failed = 0
        for raw in raw_sessions:
            try:
                pid = int(raw.ProcessId)
                if pid <= 0:
                    continue
                instance = raw.InstanceIdentifier or ""
                sid = instance or f"{pid}:{getattr(raw, 'Identifier', '')}"
                if sid not in remaining:
                    continue
                raw.SimpleAudioVolume.SetMute(1 if remaining[sid] else 0, None)
                remaining.pop(sid, None)
            except Exception as exc:
                failed += 1
                log.debug("Journal restore skipped for a session: %s", exc)
        if failed:
            self._journal.save(remaining)
        else:
            self._journal.clear()

    def _restore_all(self) -> None:
        with self._lock:
            baseline = dict(self._baseline)
            self._baseline.clear()
        if not baseline:
            self._journal.clear()
            return
        log.info("Restoring %d audio sessions", len(baseline))
        try:
            raw_sessions = list(self._session_provider())
        except Exception as exc:
            log.warning("Could not enumerate sessions for restore: %s", exc)
            self._journal.save(baseline)
            return
        remaining = dict(baseline)
        failed = 0
        for raw in raw_sessions:
            try:
                pid = int(raw.ProcessId)
                if pid <= 0:
                    continue
                instance = raw.InstanceIdentifier or ""
                sid = instance or f"{pid}:{getattr(raw, 'Identifier', '')}"
                if sid not in remaining:
                    continue
                raw.SimpleAudioVolume.SetMute(1 if remaining[sid] else 0, None)
                remaining.pop(sid, None)
            except Exception as exc:
                failed += 1
                log.debug("Restore skipped for a session: %s", exc)
        if remaining and failed:
            self._journal.save(remaining)
        else:
            # Sessions that no longer exist cannot be restored; a new session
            # starts unmuted, so the journal can be discarded.
            self._journal.clear()
