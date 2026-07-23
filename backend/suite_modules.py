"""Persisted enablement state for the static suite module registry.

Tracks which optional modules the user has enabled. Files is an always-enabled
base descriptor and is never written here. "Enabled" is a user choice stored in the
shared, irreplaceable ``user.sqlite`` in the base/suite-owned
``suite_enabled_modules`` table (prefix convention). Isolated: no Danbooru or
``core`` imports. See docs/important/SUITE_MODULE_CONTRACT.md sections 3 and 6.

This state gates module visibility and module-owned background startup. Cheap
legacy schema initialization remains mounted for compatibility, so enabling a
module does not require restarting the suite; full physical Danbooru artifact
decoupling remains incremental work.
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


def module_name(module_id: str) -> str:
    return MODULE_REGISTRY.require(module_id).name


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
