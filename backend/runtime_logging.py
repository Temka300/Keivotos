"""Persistent, dated application and HTTP access logging."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import (
    ACCESS_LOG_FILE,
    LOG_DIR,
    LOG_FILE_LIMIT_MB,
    LOG_RETENTION_FILES,
    LOG_ROLLOVER_FILES,
    RUNTIME_LOG_FILE,
)


class _UsefulRuntimeAccessFilter(logging.Filter):
    """Keep mutations and failures in runtime logs without successful read noise."""

    _READ_METHODS = {"GET", "HEAD", "OPTIONS"}

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True
        arguments = record.args
        if not isinstance(arguments, tuple) or len(arguments) < 5:
            return True
        try:
            method = str(arguments[1]).upper()
            status_code = int(arguments[4])
        except (TypeError, ValueError):
            return True
        return method not in self._READ_METHODS or status_code >= 400


def _prune_old_log_files(prefix: str, current_path: Path) -> None:
    """Keep dated logs bounded without reusing a generic filename."""
    try:
        existing = sorted(
            (
                path
                for path in LOG_DIR.glob(f"{prefix}-*.log*")
                if path.is_file() and path != current_path
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        return
    for stale_path in existing[max(0, LOG_RETENTION_FILES - 1):]:
        try:
            stale_path.unlink()
        except OSError:
            pass


def _file_handler(path: Path, formatter: logging.Formatter) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=LOG_FILE_LIMIT_MB * 1024 * 1024,
        backupCount=LOG_ROLLOVER_FILES,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    return handler


def configure_runtime_logging() -> tuple[Path, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _prune_old_log_files("danbooru-runtime", RUNTIME_LOG_FILE)
    _prune_old_log_files("danbooru-access", ACCESS_LOG_FILE)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    runtime_handler = _file_handler(RUNTIME_LOG_FILE, formatter)
    runtime_handler.addFilter(_UsefulRuntimeAccessFilter())
    access_handler = _file_handler(ACCESS_LOG_FILE, formatter)

    root_logger.handlers.clear()
    root_logger.addHandler(console)
    root_logger.addHandler(runtime_handler)

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False
    access_logger.addHandler(console)
    access_logger.addHandler(runtime_handler)
    access_logger.addHandler(access_handler)
    return RUNTIME_LOG_FILE, ACCESS_LOG_FILE
