from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from config import DATA_DB_PATH, DATA_ROOT, USER_DB_PATH
from schema import ensure_data_schema
from storage_layout import deterministic_root_id


class _DatabaseAccessGate:
    """Allow concurrent requests while giving restore a truly exclusive window."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._readers = 0
        self._writer_thread: int | None = None
        self._writer_depth = 0
        self._waiting_writers = 0

    @contextmanager
    def read(self) -> Generator[None, None, None]:
        thread_id = threading.get_ident()
        with self._condition:
            while (
                self._writer_thread not in (None, thread_id)
                or (self._waiting_writers > 0 and self._writer_thread != thread_id)
            ):
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @contextmanager
    def write(self) -> Generator[None, None, None]:
        thread_id = threading.get_ident()
        with self._condition:
            if self._writer_thread == thread_id:
                self._writer_depth += 1
            else:
                self._waiting_writers += 1
                try:
                    while self._writer_thread is not None or self._readers > 0:
                        self._condition.wait()
                    self._writer_thread = thread_id
                    self._writer_depth = 1
                finally:
                    self._waiting_writers -= 1
        try:
            yield
        finally:
            with self._condition:
                self._writer_depth -= 1
                if self._writer_depth == 0:
                    self._writer_thread = None
                    self._condition.notify_all()


_database_access_gate = _DatabaseAccessGate()


@contextmanager
def exclusive_database_access() -> Generator[None, None, None]:
    """Block new DB users and wait for live request connections to close."""
    with _database_access_gate.write():
        yield


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


@contextmanager
def get_data_db() -> Generator[sqlite3.Connection, None, None]:
    with _database_access_gate.read():
        conn = sqlite3.connect(DATA_DB_PATH, check_same_thread=False)
        conn.row_factory = _row_factory
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()


@contextmanager
def get_user_db() -> Generator[sqlite3.Connection, None, None]:
    with _database_access_gate.read():
        conn = sqlite3.connect(USER_DB_PATH, check_same_thread=False)
        conn.row_factory = _row_factory
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def local_downloaded_at(path_value: str | Path) -> str | None:
    path = Path(path_value)
    try:
        stat = path.stat()
    except OSError:
        return None
    timestamp = getattr(stat, "st_birthtime", None) or getattr(stat, "st_ctime", None) or stat.st_mtime
    return datetime.fromtimestamp(timestamp).isoformat()


def init_data_db() -> None:
    DATA_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_data_db() as conn:
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


def _upgrade_user_identity_storage(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "favorites", "file_path", "TEXT")
    _ensure_column(conn, "favorites", "local_md5", "TEXT")
    _ensure_column(conn, "favorites", "pinned_at", "TEXT")
    _ensure_column(conn, "collections", "pinned_at", "TEXT")
    _ensure_column(conn, "collection_items", "file_path", "TEXT")
    _ensure_column(conn, "collection_items", "local_md5", "TEXT")
    _ensure_column(conn, "collection_items", "pinned_at", "TEXT")
    _ensure_column(conn, "favorite_tags", "pinned_at", "TEXT")
    _ensure_column(conn, "user_image_tags", "file_path", "TEXT")
    _ensure_column(conn, "user_image_tags", "local_md5", "TEXT")
    _ensure_column(conn, "user_image_tags", "tag_category", "TEXT NOT NULL DEFAULT 'general'")
    _ensure_column(conn, "image_views", "file_path", "TEXT")
    _ensure_column(conn, "image_views", "local_md5", "TEXT")
    _ensure_column(conn, "image_views", "first_viewed_at", "TEXT")
    _ensure_column(conn, "image_views", "last_viewed_at", "TEXT")
    _ensure_column(conn, "image_views", "heart_spam_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "tag_wiki_cache", "artist_id", "INTEGER")
    _ensure_column(conn, "tag_wiki_cache", "artist_name", "TEXT")
    _ensure_column(conn, "tag_wiki_cache", "artist_group_name", "TEXT")
    _ensure_column(conn, "tag_wiki_cache", "artist_urls_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "tag_wiki_cache", "artist_urls_checked", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "artist_follows", "tag_category", "TEXT NOT NULL DEFAULT 'artist'")
    _ensure_column(conn, "artist_follows", "display_name", "TEXT")
    _ensure_column(conn, "artist_follows", "danbooru_enabled", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "artist_follows", "last_checked_at", "TEXT")
    _ensure_column(conn, "artist_follows", "notification_initialized_at", "TEXT")
    _ensure_column(conn, "artist_follows", "last_seen_danbooru_post_id", "INTEGER")
    _ensure_column(conn, "artist_follows", "notes", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "artist_follow_posts", "seen_at", "TEXT")
    _ensure_column(conn, "artist_follow_posts", "source", "TEXT NOT NULL DEFAULT 'danbooru'")
    _ensure_column(conn, "registered_folders", "path", "TEXT")
    _ensure_column(conn, "registered_folders", "root_id", "TEXT")
    _ensure_column(conn, "registered_folders", "display_name", "TEXT")
    for row in conn.execute(
        "SELECT name FROM registered_folders WHERE path IS NULL OR path=''"
    ).fetchall():
        conn.execute(
            "UPDATE registered_folders SET path=? WHERE name=?",
            (str(DATA_ROOT / row["name"]), row["name"]),
        )
    for row in conn.execute(
        "SELECT name, path FROM registered_folders WHERE root_id IS NULL OR root_id=''"
    ).fetchall():
        folder_path = Path(row["path"] or (DATA_ROOT / row["name"]))
        conn.execute(
            "UPDATE registered_folders SET root_id=? WHERE name=?",
            (deterministic_root_id(folder_path), row["name"]),
        )
    conn.execute(
        "UPDATE registered_folders SET display_name=name "
        "WHERE display_name IS NULL OR display_name=''"
    )
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_favorites_file_path
            ON favorites(file_path);
        CREATE INDEX IF NOT EXISTS idx_favorites_local_md5
            ON favorites(local_md5);
        CREATE INDEX IF NOT EXISTS idx_favorites_pinned_at
            ON favorites(pinned_at);
        CREATE INDEX IF NOT EXISTS idx_collections_pinned_at
            ON collections(pinned_at);
        CREATE INDEX IF NOT EXISTS idx_collection_items_file_path
            ON collection_items(file_path);
        CREATE INDEX IF NOT EXISTS idx_collection_items_local_md5
            ON collection_items(local_md5);
        CREATE INDEX IF NOT EXISTS idx_collection_items_pinned_at
            ON collection_items(collection_id, pinned_at);
        CREATE INDEX IF NOT EXISTS idx_favorite_tags_pinned_at
            ON favorite_tags(pinned_at);
        CREATE INDEX IF NOT EXISTS idx_user_image_tags_file
            ON user_image_tags(file_id);
        CREATE INDEX IF NOT EXISTS idx_user_image_tags_file_path
            ON user_image_tags(file_path);
        CREATE INDEX IF NOT EXISTS idx_user_image_tags_local_md5
            ON user_image_tags(local_md5);
        CREATE INDEX IF NOT EXISTS idx_user_image_tags_name
            ON user_image_tags(tag_name);
        CREATE INDEX IF NOT EXISTS idx_user_image_tags_category
            ON user_image_tags(tag_category);
        CREATE INDEX IF NOT EXISTS idx_user_image_tags_category_name
            ON user_image_tags(tag_category, tag_name);
        CREATE INDEX IF NOT EXISTS idx_image_views_file_path
            ON image_views(file_path);
        CREATE INDEX IF NOT EXISTS idx_image_views_local_md5
            ON image_views(local_md5);
        CREATE INDEX IF NOT EXISTS idx_image_views_last_viewed
            ON image_views(last_viewed_at);
        CREATE INDEX IF NOT EXISTS idx_image_views_heart_spam
            ON image_views(heart_spam_count);
        CREATE INDEX IF NOT EXISTS idx_artist_follows_added
            ON artist_follows(added_at);
        CREATE INDEX IF NOT EXISTS idx_artist_follow_posts_seen
            ON artist_follow_posts(tag_name, seen_at);
        CREATE INDEX IF NOT EXISTS idx_artist_follow_posts_post
            ON artist_follow_posts(danbooru_post_id);
        CREATE INDEX IF NOT EXISTS idx_artist_profile_assets_tag
            ON artist_profile_assets(tag_name, captured_at);
        CREATE INDEX IF NOT EXISTS idx_artist_profile_assets_identity
            ON artist_profile_assets(tag_name, platform, asset_kind, content_hash);
        CREATE INDEX IF NOT EXISTS idx_tag_removals_file_path
            ON tag_removals(file_path);
        CREATE INDEX IF NOT EXISTS idx_tag_removals_local_md5
            ON tag_removals(local_md5);
        CREATE INDEX IF NOT EXISTS idx_tag_removals_checked_at
            ON tag_removals(checked_at);
    """)

    if not DATA_DB_PATH.exists():
        return

    conn.execute("ATTACH DATABASE ? AS datadb", (str(DATA_DB_PATH),))
    try:
        conn.executescript("""
            UPDATE favorites
               SET file_path = COALESCE(file_path, (
                       SELECT path FROM datadb.files WHERE datadb.files.id = favorites.file_id
                   )),
                   local_md5 = COALESCE(local_md5, (
                       SELECT local_md5 FROM datadb.files WHERE datadb.files.id = favorites.file_id
                   ));

            UPDATE collection_items
               SET file_path = COALESCE(file_path, (
                       SELECT path FROM datadb.files WHERE datadb.files.id = collection_items.file_id
                   )),
                   local_md5 = COALESCE(local_md5, (
                       SELECT local_md5 FROM datadb.files WHERE datadb.files.id = collection_items.file_id
                   ));

            UPDATE user_image_tags
               SET file_path = COALESCE(file_path, (
                       SELECT path FROM datadb.files WHERE datadb.files.id = user_image_tags.file_id
                   )),
                   local_md5 = COALESCE(local_md5, (
                       SELECT local_md5 FROM datadb.files WHERE datadb.files.id = user_image_tags.file_id
                   ));

            UPDATE image_views
               SET file_path = COALESCE(file_path, (
                       SELECT path FROM datadb.files WHERE datadb.files.id = image_views.file_id
                   )),
                   local_md5 = COALESCE(local_md5, (
                       SELECT local_md5 FROM datadb.files WHERE datadb.files.id = image_views.file_id
                   ));
        """)
    finally:
        conn.commit()
        conn.execute("DETACH DATABASE datadb")


def init_user_db() -> None:
    USER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_user_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS favorites (
                file_id INTEGER PRIMARY KEY,
                file_path TEXT,
                local_md5 TEXT,
                pinned_at TEXT,
                added_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                pinned_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS collection_items (
                collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                file_id INTEGER NOT NULL,
                file_path TEXT,
                local_md5 TEXT,
                pinned_at TEXT,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (collection_id, file_id)
            );

            CREATE INDEX IF NOT EXISTS idx_collection_items_file
                ON collection_items(file_id);

            CREATE TABLE IF NOT EXISTS favorite_tags (
                tag_name TEXT NOT NULL,
                tag_category TEXT NOT NULL,
                pinned_at TEXT,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (tag_name, tag_category)
            );

            CREATE TABLE IF NOT EXISTS favorite_tag_combos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                tag_key TEXT NOT NULL UNIQUE,
                tags_json TEXT NOT NULL,
                added_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS blacklist_tags (
                tag_name TEXT PRIMARY KEY,
                added_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_image_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                file_path TEXT,
                local_md5 TEXT,
                tag_category TEXT NOT NULL DEFAULT 'general',
                tag_name TEXT NOT NULL,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(file_path, tag_category, tag_name)
            );

            CREATE TABLE IF NOT EXISTS image_views (
                file_id INTEGER PRIMARY KEY,
                file_path TEXT,
                local_md5 TEXT,
                view_count INTEGER NOT NULL DEFAULT 0,
                heart_spam_count INTEGER NOT NULL DEFAULT 0,
                first_viewed_at TEXT,
                last_viewed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tag_wiki_cache (
                tag_name TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                other_names_json TEXT NOT NULL DEFAULT '[]',
                body TEXT NOT NULL DEFAULT '',
                aliases_json TEXT NOT NULL DEFAULT '[]',
                implications_json TEXT NOT NULL DEFAULT '[]',
                artist_id INTEGER,
                artist_name TEXT,
                artist_group_name TEXT,
                artist_urls_json TEXT NOT NULL DEFAULT '[]',
                artist_urls_checked INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'ok',
                error TEXT,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS artist_follows (
                tag_name TEXT PRIMARY KEY,
                tag_category TEXT NOT NULL DEFAULT 'artist',
                display_name TEXT,
                danbooru_enabled INTEGER NOT NULL DEFAULT 1,
                last_checked_at TEXT,
                notification_initialized_at TEXT,
                last_seen_danbooru_post_id INTEGER,
                notes TEXT NOT NULL DEFAULT '',
                added_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS artist_follow_posts (
                tag_name TEXT NOT NULL REFERENCES artist_follows(tag_name) ON DELETE CASCADE,
                danbooru_post_id INTEGER NOT NULL,
                source TEXT NOT NULL DEFAULT 'danbooru',
                seen_at TEXT,
                discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (tag_name, danbooru_post_id)
            );

            CREATE TABLE IF NOT EXISTS artist_profile_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT NOT NULL,
                platform TEXT NOT NULL,
                asset_kind TEXT NOT NULL,
                source_profile_url TEXT NOT NULL,
                source_url TEXT NOT NULL,
                file_path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                captured_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(tag_name, platform, asset_kind, content_hash)
            );

            CREATE TABLE IF NOT EXISTS tag_removals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER,
                file_path TEXT,
                local_md5 TEXT,
                removed_tags_json TEXT NOT NULL DEFAULT '[]',
                checked_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS registered_folders (
                name TEXT PRIMARY KEY,
                added_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

        """)
        _upgrade_user_identity_storage(conn)
        conn.commit()
