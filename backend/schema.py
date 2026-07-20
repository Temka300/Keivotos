"""Authoritative SQLite schema and index migrations for the library index."""
from __future__ import annotations

import sqlite3


DATA_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    folder TEXT,
    root_id TEXT,
    relative_path TEXT,
    name TEXT NOT NULL,
    ext TEXT,
    size INTEGER,
    local_md5 TEXT,
    downloaded_at TEXT,
    matched_md5 TEXT,
    matched_by TEXT
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
    danbooru_post_id INTEGER,
    post_url TEXT,
    rating TEXT,
    score INTEGER,
    source_url TEXT,
    created_at TEXT,
    updated_at TEXT,
    parent_id INTEGER,
    has_children INTEGER,
    child_ids_json TEXT,
    width INTEGER,
    height INTEGER,
    file_ext TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_tags (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, tag_id)
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_manifest (
    media_path TEXT PRIMARY KEY,
    sidecar_path TEXT,
    sidecar_mtime INTEGER,
    sidecar_size INTEGER,
    media_mtime INTEGER,
    media_size INTEGER,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS ingest_state (
    media_path TEXT PRIMARY KEY,
    root_id TEXT,
    relative_path TEXT,
    phase TEXT NOT NULL DEFAULT 'discovered',
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    discovered_at TEXT,
    enriched_at TEXT,
    metadata_at TEXT,
    finalized_at TEXT
);
"""


DATA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder);
CREATE INDEX IF NOT EXISTS idx_files_root_relative ON files(root_id, relative_path);
CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_local_md5 ON files(local_md5);
CREATE INDEX IF NOT EXISTS idx_files_downloaded_at ON files(downloaded_at);
CREATE INDEX IF NOT EXISTS idx_files_name ON files(name, id);
CREATE INDEX IF NOT EXISTS idx_files_size ON files(size, id);
CREATE INDEX IF NOT EXISTS idx_files_folder_downloaded ON files(folder, downloaded_at, id);
CREATE INDEX IF NOT EXISTS idx_files_matched_md5 ON files(matched_md5);
CREATE INDEX IF NOT EXISTS idx_posts_danbooru_post_id ON posts(danbooru_post_id);
CREATE INDEX IF NOT EXISTS idx_posts_parent_id ON posts(parent_id);
CREATE INDEX IF NOT EXISTS idx_posts_rating ON posts(rating);
CREATE INDEX IF NOT EXISTS idx_posts_score ON posts(score);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at, id);
CREATE INDEX IF NOT EXISTS idx_posts_rating_created ON posts(rating, created_at, id);
CREATE INDEX IF NOT EXISTS idx_tags_category_name ON tags(category, name);
CREATE INDEX IF NOT EXISTS idx_post_tags_tag_post ON post_tags(tag_id, post_id);
CREATE INDEX IF NOT EXISTS idx_ingest_state_phase ON ingest_state(phase, status);
"""


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"] if isinstance(row, dict) else row[1])
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def _ensure_column(connection: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    if name not in _columns(connection, table):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def ensure_data_schema(connection: sqlite3.Connection, create_indexes: bool = True) -> None:
    """Create and additively migrate the disposable library index."""
    connection.executescript(DATA_SCHEMA)
    _ensure_column(connection, "files", "downloaded_at", "TEXT")
    _ensure_column(connection, "files", "root_id", "TEXT")
    _ensure_column(connection, "files", "relative_path", "TEXT")
    _ensure_column(connection, "posts", "parent_id", "INTEGER")
    _ensure_column(connection, "posts", "has_children", "INTEGER")
    _ensure_column(connection, "posts", "child_ids_json", "TEXT")
    if create_indexes:
        connection.executescript(DATA_INDEXES)


def create_data_indexes(connection: sqlite3.Connection) -> None:
    connection.executescript(DATA_INDEXES)
