"""Persistent application settings.

Only applications explicitly selected by the user are stored. This keeps the
JSON file small and means a selection follows an app across restarts.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Iterable

from .paths import settings_path

log = logging.getLogger(__name__)

SETTINGS_VERSION = 1
MIN_INTERVAL = 0.35
MAX_INTERVAL = 5.0


def normalize_key(key: str) -> str:
    return key.strip().casefold()


class Settings:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or settings_path()
        self._lock = threading.RLock()
        self._is_new = not os.path.exists(self.path)
        self.enabled = True
        self.poll_interval = 0.8
        self.close_to_tray = True
        self.start_minimized = False
        self.tray_hint_shown = False
        self.auto_select_new = True
        self.restore_on_exit = True
        self.apps: dict[str, dict[str, str]] = {}
        self.ignored: set[str] = set()
        self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log.warning("Could not read settings (%s); using defaults", exc)
            self._quarantine_broken_file()
            return

        self.enabled = bool(data.get("enabled", True))
        try:
            interval = float(data.get("poll_interval_sec", 0.8))
        except (TypeError, ValueError):
            interval = 0.8
        self.poll_interval = min(MAX_INTERVAL, max(MIN_INTERVAL, interval))
        self.close_to_tray = bool(data.get("close_to_tray", True))
        self.start_minimized = bool(data.get("start_minimized", False))
        self.tray_hint_shown = bool(data.get("tray_hint_shown", False))
        self.auto_select_new = bool(data.get("auto_select_new", True))
        self.restore_on_exit = bool(data.get("restore_on_exit", True))
        ignored = data.get("ignored", [])
        if isinstance(ignored, list):
            self.ignored = {str(key) for key in ignored if isinstance(key, str)}

        apps = data.get("apps", {})
        if isinstance(apps, dict):
            for key, meta in apps.items():
                if not isinstance(key, str) or not isinstance(meta, dict):
                    continue
                if not meta.get("selected", True):
                    continue
                clean = {
                    "name": str(meta.get("name") or ""),
                    "exe_name": str(meta.get("exe_name") or ""),
                    "exe_path": str(meta.get("exe_path") or ""),
                }
                self.apps[key] = clean

    def _quarantine_broken_file(self) -> None:
        try:
            broken = f"{self.path}.broken-{int(time.time())}"
            os.replace(self.path, broken)
            log.info("Moved unreadable settings to %s", broken)
        except OSError:
            pass

    # ------------------------------------------------------------------ save
    def save(self) -> None:
        with self._lock:
            data = {
                "version": SETTINGS_VERSION,
                "enabled": bool(self.enabled),
                "poll_interval_sec": round(float(self.poll_interval), 2),
                "close_to_tray": bool(self.close_to_tray),
                "start_minimized": bool(self.start_minimized),
                "tray_hint_shown": bool(self.tray_hint_shown),
                "auto_select_new": bool(self.auto_select_new),
                "restore_on_exit": bool(self.restore_on_exit),
                "ignored": sorted(self.ignored),
                "apps": self.apps,
            }
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                temp = f"{self.path}.tmp"
                with open(temp, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.replace(temp, self.path)
                except OSError:
                    # Some managed folders refuse atomic replacement. A direct
                    # write is better than losing the selection.
                    with open(self.path, "w", encoding="utf-8") as handle:
                        json.dump(data, handle, ensure_ascii=False, indent=2)
                    try:
                        os.unlink(temp)
                    except OSError:
                        pass
            except OSError as exc:
                log.error("Could not save settings: %s", exc)

    # --------------------------------------------------------------- queries
    @property
    def is_new(self) -> bool:
        return self._is_new

    def mark_onboarded(self) -> None:
        self._is_new = False

    def selected_keys(self) -> set[str]:
        with self._lock:
            return set(self.apps.keys())

    def selected_apps(self) -> list[dict[str, str]]:
        with self._lock:
            result = []
            for key, meta in self.apps.items():
                item = dict(meta)
                item["key"] = key
                result.append(item)
            return result

    def is_selected(self, key: str) -> bool:
        with self._lock:
            return key in self.apps

    def ignored_keys(self) -> set[str]:
        with self._lock:
            return set(self.ignored)

    def is_ignored(self, key: str) -> bool:
        with self._lock:
            return key in self.ignored

    # --------------------------------------------------------------- changes
    def set_app_selected(
        self, key: str, selected: bool, meta: dict[str, str] | None = None
    ) -> bool:
        """Select or deselect an app. Returns True when something changed."""
        with self._lock:
            changed = False
            if selected:
                clean = {
                    "name": str((meta or {}).get("name") or ""),
                    "exe_name": str((meta or {}).get("exe_name") or ""),
                    "exe_path": str((meta or {}).get("exe_path") or ""),
                }
                if self.apps.get(key) != clean:
                    self.apps[key] = clean
                    changed = True
                if key in self.ignored:
                    self.ignored.discard(key)
                    changed = True
            else:
                if key in self.apps:
                    del self.apps[key]
                    changed = True
                if key not in self.ignored:
                    self.ignored.add(key)
                    changed = True
            if changed:
                self.save()
            return changed

    def select_all(
        self,
        items: Iterable[tuple[str, dict[str, str]]],
        *,
        clear_ignored: bool = False,
    ) -> int:
        changed = 0
        ignored_changed = False
        with self._lock:
            for key, meta in items:
                if clear_ignored:
                    if key in self.ignored:
                        self.ignored.discard(key)
                        ignored_changed = True
                elif key in self.ignored:
                    continue
                if key in self.apps:
                    continue
                self.apps[key] = {
                    "name": str(meta.get("name") or ""),
                    "exe_name": str(meta.get("exe_name") or ""),
                    "exe_path": str(meta.get("exe_path") or ""),
                }
                changed += 1
            if changed or ignored_changed:
                self.save()
        return changed

    def clear_all(self, running_keys: Iterable[str] = ()) -> int:
        with self._lock:
            count = len(self.apps)
            before = len(self.ignored)
            self.ignored.update(running_keys)
            if count or len(self.ignored) != before:
                self.apps.clear()
                self.save()
            return count

    def set_auto_select_new(self, value: bool) -> None:
        with self._lock:
            if self.auto_select_new == value:
                return
            self.auto_select_new = value
            self.save()

    def set_restore_on_exit(self, value: bool) -> None:
        with self._lock:
            if self.restore_on_exit == value:
                return
            self.restore_on_exit = value
            self.save()

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            if self.enabled == enabled:
                return
            self.enabled = enabled
            self.save()

    def set_poll_interval(self, seconds: float) -> None:
        with self._lock:
            value = min(MAX_INTERVAL, max(MIN_INTERVAL, float(seconds)))
            if abs(value - self.poll_interval) < 0.001:
                return
            self.poll_interval = value
            self.save()

    def set_close_to_tray(self, value: bool) -> None:
        with self._lock:
            if self.close_to_tray == value:
                return
            self.close_to_tray = value
            self.save()

    def set_start_minimized(self, value: bool) -> None:
        with self._lock:
            if self.start_minimized == value:
                return
            self.start_minimized = value
            self.save()

    def set_tray_hint_shown(self) -> None:
        with self._lock:
            if self.tray_hint_shown:
                return
            self.tray_hint_shown = True
            self.save()

    def forget_missing(self, running_keys: set[str]) -> int:
        with self._lock:
            missing = [key for key in self.apps if key not in running_keys]
            for key in missing:
                del self.apps[key]
            if missing:
                self.save()
            return len(missing)

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "poll_interval_sec": self.poll_interval,
                "close_to_tray": self.close_to_tray,
                "start_minimized": self.start_minimized,
                "auto_select_new": self.auto_select_new,
                "selected": len(self.apps),
                "ignored": len(self.ignored),
            }
