"""Filesystem locations used by the application."""

from __future__ import annotations

import os
import sys

APP_NAME = "QuietFocus"
APP_TITLE = "静界 QuietFocus"


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts: str) -> str:
    """Return a path to a bundled resource, also when running from PyInstaller."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = project_root()
    return os.path.join(base, *parts)


def data_dir() -> str:
    override = os.environ.get("QUIETFOCUS_DATA_DIR")
    if override:
        path = os.path.abspath(os.path.expanduser(override))
    else:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def settings_path() -> str:
    return os.path.join(data_dir(), "settings.json")


def log_path() -> str:
    return os.path.join(data_dir(), "quietfocus.log")


def restore_journal_path() -> str:
    return os.path.join(data_dir(), "restore.json")
