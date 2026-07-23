"""Disposable file-index schema for the Files base (V1.1.0).

``files.sqlite`` holds only facts derivable from disk (path, name, ext, size,
mtime) plus a lazily-computed content hash. It is rebuildable at any time from
the filesystem, so it is never backed up and never authoritative. User-created
data (sources, roles, favorites) belongs in ``user.sqlite`` instead — see
docs/important/SUITE_MODULE_CONTRACT.md sections 3 and 5.
"""
from __future__ import annotations

import sqlite3


FILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS files_index (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL,
    parent TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    ext TEXT,
    is_dir INTEGER NOT NULL DEFAULT 0,
    size INTEGER,
    mtime INTEGER,
    content_hash TEXT,
    hashed_at TEXT,
    indexed_at TEXT,
    seen_at TEXT,
    available INTEGER NOT NULL DEFAULT 1
);
"""

FILES_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_files_index_source_parent
    ON files_index(source_id, parent, is_dir, name);
CREATE INDEX IF NOT EXISTS idx_files_index_name ON files_index(name);
CREATE INDEX IF NOT EXISTS idx_files_index_ext ON files_index(ext);
CREATE INDEX IF NOT EXISTS idx_files_index_size ON files_index(size);
CREATE INDEX IF NOT EXISTS idx_files_index_hash ON files_index(content_hash);
CREATE INDEX IF NOT EXISTS idx_files_index_available ON files_index(source_id, available);
"""


def ensure_files_schema(connection: sqlite3.Connection) -> None:
    """Create the file-index tables and indexes if they do not already exist.

    Idempotent and additive: safe to call on every connection open.
    """
    connection.executescript(FILES_SCHEMA)
    connection.executescript(FILES_INDEXES)
    connection.commit()
