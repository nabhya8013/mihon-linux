"""
Central logging configuration.

The app previously mixed bare `print()` calls with per-module `logging` loggers
that had no handler attached, so extension diagnostics went to stderr in an
inconsistent format and nothing was ever written to disk. `configure_logging()`
is called once at startup and gives every module the same console + rotating
file output.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from .database import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "mihon.log"

_CONSOLE_FORMAT = "%(levelname)-7s %(name)-18s %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)-18s %(message)s"

_configured = False


def configure_logging(level: int | str | None = None) -> None:
    """
    Install console + rotating-file handlers on the root logger.

    Idempotent: safe to call from both `run.py` and `MihonApp` startup.
    Override the level with the ``MIHON_LOG_LEVEL`` environment variable
    (e.g. ``MIHON_LOG_LEVEL=DEBUG python3 run.py``).
    """
    global _configured
    if _configured:
        return

    if level is None:
        level = os.environ.get("MIHON_LOG_LEVEL", "INFO")
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    console.setLevel(level)
    root.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        file_handler.setLevel(logging.DEBUG)
        root.addHandler(file_handler)
    except OSError as exc:
        # A read-only or missing data dir must not stop the app from starting.
        root.warning("File logging disabled: %s", exc)

    # Third-party noise that is not useful at INFO.
    for noisy in ("urllib3", "curl_cffi", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def log_path() -> Path:
    return LOG_FILE
