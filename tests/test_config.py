"""Settings persistence tests."""

from __future__ import annotations

import json
import os
import unittest
import uuid
from pathlib import Path

from quietfocus.config import Settings

META = {"name": "Music", "exe_name": "Music.exe", "exe_path": r"C:\Fake\Music.exe"}
KEY = "path:c:\\fake\\music.exe"


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1] / ".test-tmp"
        root.mkdir(exist_ok=True)
        self.dir = os.path.join(root, f"settings-{os.getpid()}-{uuid.uuid4().hex}")
        os.makedirs(self.dir)
        self.path = os.path.join(self.dir, "settings.json")

    def test_defaults_and_first_run(self):
        settings = Settings(self.path)
        self.assertTrue(settings.is_new)
        self.assertTrue(settings.enabled)
        self.assertTrue(settings.auto_select_new)
        self.assertEqual(settings.selected_keys(), set())

    def test_unselected_is_ignored_and_persisted(self):
        settings = Settings(self.path)
        settings.set_app_selected(KEY, True, META)
        self.assertTrue(settings.is_selected(KEY))
        self.assertFalse(settings.is_ignored(KEY))
        settings.set_app_selected(KEY, False)
        self.assertFalse(settings.is_selected(KEY))
        self.assertTrue(settings.is_ignored(KEY))

        reloaded = Settings(self.path)
        self.assertFalse(reloaded.is_selected(KEY))
        self.assertTrue(reloaded.is_ignored(KEY))

        # Auto-select must not resurrect explicitly unchecked apps.
        reloaded.select_all([(KEY, META)])
        self.assertFalse(reloaded.is_selected(KEY))

        # An explicit "select all" clears the exclusion.
        reloaded.select_all([(KEY, META)], clear_ignored=True)
        self.assertTrue(reloaded.is_selected(KEY))
        self.assertFalse(reloaded.is_ignored(KEY))

    def test_clear_all_ignores_current_running_apps(self):
        settings = Settings(self.path)
        settings.set_app_selected(KEY, True, META)
        settings.clear_all({KEY})
        self.assertEqual(settings.selected_keys(), set())
        self.assertTrue(settings.is_ignored(KEY))
        settings.select_all([(KEY, META)])
        self.assertFalse(settings.is_selected(KEY))

    def test_bom_is_accepted(self):
        with open(self.path, "w", encoding="utf-8-sig") as handle:
            json.dump({"enabled": False, "apps": {}}, handle)
        settings = Settings(self.path)
        self.assertFalse(settings.enabled)

    def test_interval_clamped(self):
        settings = Settings(self.path)
        settings.set_poll_interval(99)
        self.assertLessEqual(settings.poll_interval, 5.0)
        settings.set_poll_interval(0)
        self.assertGreaterEqual(settings.poll_interval, 0.35)

    def test_auto_select_setting_persists(self):
        settings = Settings(self.path)
        settings.set_auto_select_new(False)
        reloaded = Settings(self.path)
        self.assertFalse(reloaded.auto_select_new)


if __name__ == "__main__":
    unittest.main()
