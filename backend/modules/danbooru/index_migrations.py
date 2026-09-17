"""Danbooru index initialization and legacy download-date normalization."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, ContextManager

from database import _ensure_column
from modules.danbooru.schema import ensure_data_schema


def local_downloaded_at(path_value: str | Path) -> str | None:
    path = Path(path_value)
    try:
        stat = path.stat()
    except OSError:
        return None
    timestamp = getattr(stat, "st_birthtime", None) or getattr(stat, "st_ctime", None) or stat.st_mtime
    return datetime.fromtimestamp(timestamp).isoformat()


def initialize_index(data_db_path: Path, connection_factory: Callable[[], ContextManager[sqlite3.Connection]]) -> None:
    data_db_path.parent.mkdir(parents=True, exist_ok=True)
    with connection_factory() as conn:
        ensure_data_schema(conn)
        _ensure_column(conn, "files", "downloaded_at", "TEXT")
        _ensure_column(conn, "posts", "parent_id", "INTEGER")
        _ensure_column(conn, "posts", "has_children", "INTEGER")
        _ensure_column(conn, "posts", "child_ids_json", "TEXT")
        conn.execute("UPDATE posts SET rating='u' WHERE rating IS NULL OR rating=''")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_files_downloaded_at ON files(downloaded_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_posts_parent_id ON posts(parent_id)"
        )
        rows = conn.execute(
            """SELECT id, path FROM files
               WHERE downloaded_at IS NULL
                  OR downloaded_at = ''
                  OR downloaded_at LIKE '%+00:00'
                  OR downloaded_at LIKE '%Z'"""
        ).fetchall()
        for row in rows:
            downloaded_at = local_downloaded_at(row["path"])
            if downloaded_at:
                conn.execute(
                    "UPDATE files SET downloaded_at=? WHERE id=?",
                    (downloaded_at, row["id"]),
                )
        conn.commit()


