"""Suite-owned user settings, independent of optional module tables."""
from __future__ import annotations

import sqlite3

USER_SCHEMA = """            CREATE TABLE IF NOT EXISTS user_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

        """


def ensure_suite_user_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(USER_SCHEMA)
