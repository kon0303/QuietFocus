"""Crash-safe journal of mute states changed by QuietFocus.

Without this, a forced kill (or power loss) would leave applications muted
forever because QuietFocus is the only component that knows the original
state. The journal is written before a mute is applied and replayed on the
next start.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Mapping

log = logging.getLogger(__name__)


class RestoreJournal:
    def __init__(self, path: str) -> None:
        self.path = path

    def load(self) -> dict[str, bool]:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            sessions = data.get("sessions", {}) if isinstance(data, dict) else {}
            result: dict[str, bool] = {}
            if isinstance(sessions, dict):
                for sid, entry in sessions.items():
                    if not isinstance(sid, str) or not isinstance(entry, dict):
                        continue
                    result[sid] = bool(entry.get("baseline_muted", False))
            return result
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log.warning("Could not read restore journal: %s", exc)
            return {}

    def save(self, baseline: Mapping[str, bool]) -> None:
        if not baseline:
            self.clear()
            return
        data = {
            "version": 1,
            "sessions": {
                sid: {"baseline_muted": bool(muted)}
                for sid, muted in baseline.items()
            },
        }
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            temp = f"{self.path}.tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.replace(temp, self.path)
            except OSError:
                with open(self.path, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False)
                try:
                    os.unlink(temp)
                except OSError:
                    pass
        except OSError as exc:
            log.warning("Could not write restore journal: %s", exc)

    def clear(self) -> None:
        try:
            if os.path.exists(self.path):
                os.unlink(self.path)
        except OSError as exc:
            log.debug("Could not clear restore journal: %s", exc)
