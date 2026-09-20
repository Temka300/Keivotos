"""Small rotating recovery checkpoints for the irreplaceable user database."""
from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import (
    USER_DB_PATH, USER_CHECKPOINT_DIR, PRESERVED_USER_CHECKPOINT_DIR,
    LEGACY_USER_CHECKPOINT_DIRS, check_recovery_path,
)


CHECKPOINT_DIR = USER_CHECKPOINT_DIR
PRESERVED_CHECKPOINT_DIR = PRESERVED_USER_CHECKPOINT_DIR
logger = logging.getLogger(__name__)
CHECKPOINT_RETENTION = 5
_checkpoint_lock = threading.Lock()


def _check_sqlite(path: Path) -> None:
    connection = sqlite3.connect(path, timeout=60)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    if not result or str(result[0]).lower() != "ok":
        raise RuntimeError(f"SQLite quick_check failed for {path}")


def _snapshot(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(source, timeout=60)
    try:
        source_connection.execute("VACUUM INTO ?", (str(destination),))
    finally:
        source_connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checkpoints() -> list[Path]:
    if not CHECKPOINT_DIR.is_dir():
        return []
    return sorted(
        (path for path in CHECKPOINT_DIR.glob("user_*.sqlite") if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )


def preserve_legacy_checkpoints() -> None:
    """Copy legacy bytes into a non-rotating archive; never alter the originals.

    Content namespaces preserve same-name snapshots with different bytes and
    make repeated startup resumable. Only verified complete copies are published.
    A bad legacy source is logged independently of new suite checkpoint creation.
    Caller holds _checkpoint_lock.
    """
    for directory in LEGACY_USER_CHECKPOINT_DIRS:
        try:
            check_recovery_path(directory)
            if not directory.is_dir() or directory.resolve() == CHECKPOINT_DIR.resolve():
                continue
            namespace = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
            for source in sorted(directory.glob("user_*.sqlite")):
                temporary = None
                try:
                    check_recovery_path(source)
                    if not source.is_file():
                        continue
                    digest = _sha256(source)
                    destination = PRESERVED_CHECKPOINT_DIR / namespace / digest / source.name
                    check_recovery_path(destination)
                    if destination.exists():
                        if not destination.is_file() or _sha256(destination) != digest:
                            raise RuntimeError(f"Conflicting preserved checkpoint: {destination}")
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".partial", delete=False) as handle:
                        temporary = Path(handle.name)
                    shutil.copy2(source, temporary)
                    if _sha256(temporary) != digest or _sha256(source) != digest:
                        raise RuntimeError(f"Legacy checkpoint changed while copying: {source}")
                    # Atomic publication without replacing any existing history.
                    try:
                        os.link(temporary, destination)
                    except FileExistsError:
                        if _sha256(destination) != digest:
                            raise RuntimeError(f"Conflicting preserved checkpoint: {destination}")
                except (OSError, RuntimeError) as exc:
                    logger.warning("Could not preserve legacy checkpoint %s: %s", source, exc)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
        except (OSError, RuntimeError) as exc:
            logger.warning("Could not read legacy recovery directory %s: %s", directory, exc)


def _preserved_count() -> int:
    check_recovery_path(PRESERVED_CHECKPOINT_DIR)
    count = 0
    # Explicit levels avoid recursively following directory links.
    for source_dir in PRESERVED_CHECKPOINT_DIR.glob("*"):
        if source_dir.is_symlink() or not source_dir.is_dir():
            continue
        for digest_dir in source_dir.glob("*"):
            if digest_dir.is_symlink() or not digest_dir.is_dir():
                continue
            count += sum(path.is_file() and not path.is_symlink() for path in digest_dir.glob("user_*.sqlite"))
    return count


def local_recovery_status() -> dict[str, Any]:
    checkpoints = _checkpoints()
    latest = checkpoints[0] if checkpoints else None
    return {
        "enabled": False,
        "directory": str(CHECKPOINT_DIR),
        "retention": CHECKPOINT_RETENTION,
        "preserved_directory": str(PRESERVED_CHECKPOINT_DIR),
        "preserved_count": _preserved_count(),
        "count": len(checkpoints),
        "latest_name": latest.name if latest else None,
        "latest_path": str(latest) if latest else None,
        "latest_at": (
            datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc).isoformat()
            if latest
            else None
        ),
    }


def _next_checkpoint_stamp() -> str:
    """Keep filenames unique and ordered even within one filesystem clock tick."""
    current = datetime.now(timezone.utc)
    for path in _checkpoints():
        match = re.match(r"user_(\d{8}_\d{6}_\d{6})_", path.name)
        if match is None:
            continue
        try:
            previous = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S_%f").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if previous >= current:
            current = previous + timedelta(microseconds=1)
    return current.strftime("%Y%m%d_%H%M%S_%f")


def create_local_recovery_checkpoint(reason: str = "manual") -> dict[str, Any]:
    """Create a verified snapshot unless the newest checkpoint is identical."""
    with _checkpoint_lock:
        if not USER_DB_PATH.is_file():
            raise FileNotFoundError(f"User database does not exist: {USER_DB_PATH}")
        _check_sqlite(USER_DB_PATH)
        check_recovery_path(CHECKPOINT_DIR)
        preserve_legacy_checkpoints()
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = _next_checkpoint_stamp()
        safe_reason = re.sub(r"[^a-z0-9_-]+", "-", reason.strip().lower()).strip("-") or "manual"
        temporary = CHECKPOINT_DIR / f".{stamp}_{safe_reason}.partial"
        final = CHECKPOINT_DIR / f"user_{stamp}_{safe_reason}.sqlite"
        try:
            _snapshot(USER_DB_PATH, temporary)
            _check_sqlite(temporary)
            checkpoints = _checkpoints()
            if checkpoints and _sha256(checkpoints[0]) == _sha256(temporary):
                temporary.unlink(missing_ok=True)
                return {
                    **local_recovery_status(),
                    "status": "unchanged",
                    "created": False,
                    "message": "User data is unchanged; the newest local recovery checkpoint is already current.",
                }
            os.replace(temporary, final)
            checkpoints = _checkpoints()
            for stale in checkpoints[CHECKPOINT_RETENTION:]:
                stale.unlink(missing_ok=True)
            return {
                **local_recovery_status(),
                "status": "created",
                "created": True,
                "message": f"Created local recovery checkpoint {final.name}.",
            }
        finally:
            temporary.unlink(missing_ok=True)
