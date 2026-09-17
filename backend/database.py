from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from config import DATA_DB_PATH, DATA_ROOT, USER_DB_PATH, MODULE_REGISTRY
from user_schema import USER_SCHEMA as SUITE_USER_SCHEMA
from database_connections import (
    _DatabaseAccessGate, _database_access_gate, _row_factory,
    connect_database, exclusive_database_access,
)


@contextmanager
def get_data_db() -> Generator[sqlite3.Connection, None, None]:
    with connect_database(DATA_DB_PATH) as conn:
        yield conn


@contextmanager
def get_user_db() -> Generator[sqlite3.Connection, None, None]:
    with connect_database(USER_DB_PATH) as conn:
        yield conn


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


def init_data_db(enabled_modules: set[str] | None = None) -> None:
    """Initialize the installed index owner, optionally restricted to enabled modules."""
    owner = MODULE_REGISTRY.get("danbooru")
    if owner is None or (enabled_modules is not None and owner.slug not in enabled_modules):
        return
    initializer = owner.index_initializer
    if initializer is None:
        raise RuntimeError("Danbooru index initializer is not registered")
    initializer(DATA_DB_PATH, get_data_db)


def init_user_db(enabled_modules: set[str] | None = None) -> None:
    """Initialize suite tables and, when selected, the installed owner's tables."""
    USER_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    owner = MODULE_REGISTRY.get("danbooru")
    if owner is None or (enabled_modules is not None and owner.slug not in enabled_modules):
        with get_user_db() as conn:
            conn.executescript(SUITE_USER_SCHEMA)
            conn.commit()
        return
    if owner.user_schema_provider is None or owner.user_migrator is None:
        raise RuntimeError("Danbooru user-table initialization is not registered")
    with get_user_db() as conn:
        conn.executescript(owner.user_schema_provider() + SUITE_USER_SCHEMA)
        owner.user_migrator(conn, DATA_DB_PATH, DATA_ROOT)
        conn.commit()
