"""Logging configuration."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from .paths import log_path


def configure_logging(debug: bool = False) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_path(), maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        pass

    # A console is normally absent in a windowed EXE, but this is useful while
    # developing and when started from a terminal.
    if sys.stderr is not None and (not getattr(sys, "frozen", False) or debug):
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

    if not root.handlers:
        root.addHandler(logging.NullHandler())

    logging.getLogger("PIL").setLevel(logging.WARNING)
