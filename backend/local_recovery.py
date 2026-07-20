"""Small rotating recovery checkpoints for the irreplaceable user database."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import METADATA_DIR, USER_DB_PATH


CHECKPOINT_DIR = METADATA_DIR / "local_recovery" / "user_database"
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


def local_recovery_status() -> dict[str, Any]:
    checkpoints = _checkpoints()
    latest = checkpoints[0] if checkpoints else None
    return {
        "enabled": True,
        "directory": str(CHECKPOINT_DIR),
        "retention": CHECKPOINT_RETENTION,
        "count": len(checkpoints),
        "latest_name": latest.name if latest else None,
        "latest_path": str(latest) if latest else None,
        "latest_at": (
            datetime.fromtimestamp(latest.stat().st_mtime, timezone.utc).isoformat()
            if latest
            else None
        ),
    }


def create_local_recovery_checkpoint(reason: str = "manual") -> dict[str, Any]:
    """Create a verified snapshot unless the newest checkpoint is identical."""
    with _checkpoint_lock:
        if not USER_DB_PATH.is_file():
            raise FileNotFoundError(f"User database does not exist: {USER_DB_PATH}")
        _check_sqlite(USER_DB_PATH)
        CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
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
