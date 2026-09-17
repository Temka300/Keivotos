"""Persisted enablement state for the static suite module registry.

Tracks which optional modules the user has enabled. Files is an always-enabled
base descriptor and is never written here. "Enabled" is a user choice stored in the
shared, irreplaceable ``user.sqlite`` in the base/suite-owned
``suite_enabled_modules`` table (prefix convention). Isolated: no Danbooru or
``core`` imports. See docs/important/SUITE_MODULE_CONTRACT.md sections 3 and 6.

This state gates module initialization, live workers and HTTP/folder operations.
Disabled modules retain their data; Files remains available.
"""
from __future__ import annotations

import sqlite3

from config import MODULE_REGISTRY
from module_descriptor import ModuleDescriptor


SUITE_MODULES_SCHEMA = """
CREATE TABLE IF NOT EXISTS suite_enabled_modules (
    module TEXT PRIMARY KEY,
    enabled_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

def ensure_schema(user_conn: sqlite3.Connection) -> None:
    """Create the enabled-modules table if absent (idempotent, additive)."""
    user_conn.executescript(SUITE_MODULES_SCHEMA)
    user_conn.commit()


def descriptors() -> tuple[ModuleDescriptor, ...]:
    return tuple(MODULE_REGISTRY)


def is_known(module_id: str) -> bool:
    return MODULE_REGISTRY.get(module_id) is not None


def enabled_ids(user_conn: sqlite3.Connection) -> set[str]:
    rows = user_conn.execute("SELECT module FROM suite_enabled_modules").fetchall()
    return {row["module"] for row in rows}


def set_enabled(user_conn: sqlite3.Connection, module_id: str, enabled: bool) -> None:
    descriptor = MODULE_REGISTRY.require(module_id)
    if not descriptor.disableable:
        if not enabled:
            raise ValueError(f"{descriptor.name} is the required suite base")
        return
    if enabled:
        user_conn.execute(
            "INSERT OR IGNORE INTO suite_enabled_modules (module) VALUES (?)",
            (module_id,),
        )
    else:
        user_conn.execute(
            "DELETE FROM suite_enabled_modules WHERE module = ?", (module_id,)
        )
    user_conn.commit()


def require_enabled(module_id: str) -> None:
    """Reject unavailable owners without opening or initializing their storage."""
    from database import get_user_db

    descriptor = MODULE_REGISTRY.get(module_id)
    if descriptor is None:
        raise RuntimeError(f"Module {module_id} is not installed")
    if descriptor.is_base:
        return
    with get_user_db() as connection:
        # Suite bootstrap owns this table. A read failure must not admit work.
        enabled = enabled_ids(connection)
    if module_id not in enabled:
        raise RuntimeError(f"Enable {descriptor.name} before using its operations")
