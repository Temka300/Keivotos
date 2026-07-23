"""Registered sources for the Files base (V1.1.0).

A "source" is a folder the user added to the base to browse. Sources are
user-created data, so they live in the shared, irreplaceable ``user.sqlite`` —
not in the disposable ``files.sqlite`` index. The base owns and ensures its own
``files_sources`` table (prefix convention), so Danbooru's ``init_user_db`` need
not know about it. See docs/important/SUITE_MODULE_CONTRACT.md sections 3 and 4.

This module is isolated: no import of Danbooru modules or ``core``. Path-safety
validation takes the forbidden paths as an explicit argument so it stays pure
and testable; the HTTP layer supplies them from configuration.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path


FILES_SOURCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS files_sources (
    source_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'files',
    visible INTEGER NOT NULL DEFAULT 1,
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass(frozen=True)
class Source:
    source_id: str
    path: str
    display_name: str
    role: str
    visible: bool
    added_at: str | None


def ensure_sources_schema(user_conn: sqlite3.Connection) -> None:
    """Create the ``files_sources`` table if absent (idempotent, additive)."""
    user_conn.executescript(FILES_SOURCES_SCHEMA)
    columns: set[str] = set()
    for row in user_conn.execute("PRAGMA table_info(files_sources)").fetchall():
        try:
            columns.add(str(row["name"]))
        except (KeyError, TypeError):
            columns.add(str(row[1]))
    if "visible" not in columns:
        user_conn.execute(
            "ALTER TABLE files_sources ADD COLUMN visible INTEGER NOT NULL DEFAULT 1"
        )
    user_conn.commit()


def canonical_role(role: str) -> str:
    """Expose the old ``base`` spelling as the Files descriptor slug."""
    normalized = role.strip().casefold()
    return "files" if normalized == "base" else normalized


def deterministic_source_id(path: str | Path) -> str:
    """A stable id derived from the absolute path, independent of display name."""
    normalized = os.path.normcase(str(Path(path).expanduser().resolve(strict=False)))
    return "src-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def is_strict_descendant_path(path: str | Path, parent: str | Path) -> bool:
    """Whether ``path`` is below ``parent`` after resolving both paths."""
    resolved = Path(path).expanduser().resolve(strict=False)
    resolved_parent = Path(parent).expanduser().resolve(strict=False)
    if os.path.normcase(str(resolved)) == os.path.normcase(str(resolved_parent)):
        return False
    try:
        return os.path.commonpath(
            [os.path.normcase(str(resolved)), os.path.normcase(str(resolved_parent))]
        ) == os.path.normcase(str(resolved_parent))
    except ValueError:
        return False


def descendant_sources(source: Source, candidates: list[Source]) -> list[Source]:
    """Return registered sources nested below ``source``, nearest first."""
    nested = [
        candidate
        for candidate in candidates
        if candidate.source_id != source.source_id
        and is_strict_descendant_path(candidate.path, source.path)
    ]
    return sorted(nested, key=lambda candidate: len(Path(candidate.path).parts))


def nearest_ancestor_source(path: str | Path, candidates: list[Source]) -> Source | None:
    """Return the deepest registered source containing ``path``."""
    ancestors = [
        candidate
        for candidate in candidates
        if is_strict_descendant_path(path, candidate.path)
    ]
    if not ancestors:
        return None
    return max(ancestors, key=lambda candidate: len(Path(candidate.path).parts))


def unsafe_source_reason(path: str | Path, forbidden_paths: list[Path]) -> str | None:
    """Return a human reason if ``path`` may not be registered, else ``None``.

    Blocks drive roots and any of Keivotos's own generated folders (databases,
    credentials, logs, backups). ``forbidden_paths`` is supplied by the caller so
    this stays independent of configuration.
    """
    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.exists():
        return "Folder does not exist"
    if not resolved.is_dir():
        return "Not a folder"
    anchor = Path(resolved.anchor).resolve(strict=False) if resolved.anchor else None
    if anchor is not None and resolved == anchor:
        return "Register a specific folder, not an entire drive root"
    for forbidden in forbidden_paths:
        fenced = Path(forbidden).resolve(strict=False)
        if resolved == fenced or fenced in resolved.parents or resolved in fenced.parents:
            return "Cannot register Keivotos's own data folders"
    return None


def _row_to_source(row: sqlite3.Row) -> Source:
    return Source(
        source_id=row["source_id"],
        path=row["path"],
        display_name=row["display_name"],
        role=canonical_role(row["role"]),
        visible=bool(row["visible"]),
        added_at=row["added_at"],
    )


def register_source(
    user_conn: sqlite3.Connection,
    path: str | Path,
    display_name: str | None = None,
    role: str = "files",
) -> Source:
    """Register ``path`` as a source (idempotent by resolved path). Returns it."""
    resolved = Path(path).expanduser().resolve(strict=False)
    source_id = deterministic_source_id(resolved)
    existing = get_source(user_conn, source_id)
    if existing is not None:
        return existing
    name = display_name.strip() if display_name and display_name.strip() else resolved.name
    user_conn.execute(
        "INSERT INTO files_sources (source_id, path, display_name, role, visible) VALUES (?, ?, ?, ?, 1)",
        (source_id, str(resolved), name, canonical_role(role)),
    )
    user_conn.commit()
    registered = get_source(user_conn, source_id)
    assert registered is not None
    return registered


def list_sources(user_conn: sqlite3.Connection, *, visible_only: bool = False) -> list[Source]:
    query = (
        "SELECT source_id, path, display_name, role, visible, added_at FROM files_sources"
    )
    if visible_only:
        query += " WHERE visible<>0"
    query += " ORDER BY added_at ASC, display_name COLLATE NOCASE ASC"
    rows = user_conn.execute(query).fetchall()
    return [_row_to_source(row) for row in rows]


def get_source(user_conn: sqlite3.Connection, source_id: str) -> Source | None:
    row = user_conn.execute(
        "SELECT source_id, path, display_name, role, visible, added_at FROM files_sources "
        "WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    return _row_to_source(row) if row is not None else None


def remove_source(user_conn: sqlite3.Connection, source_id: str) -> bool:
    """Forget a source (un-index only). Never touches files on disk."""
    removed = user_conn.execute(
        "DELETE FROM files_sources WHERE source_id = ?", (source_id,)
    ).rowcount
    user_conn.commit()
    return removed > 0


def update_source(
    user_conn: sqlite3.Connection,
    source_id: str,
    *,
    display_name: str | None = None,
    role: str | None = None,
    visible: bool | None = None,
    commit: bool = True,
) -> Source | None:
    """Update registry presentation/assignment without touching disk files."""
    assignments: list[str] = []
    parameters: list[object] = []
    if display_name is not None:
        name = display_name.strip()
        if not name:
            raise ValueError("Folder display name cannot be blank")
        assignments.append("display_name=?")
        parameters.append(name)
    if role is not None:
        assignments.append("role=?")
        parameters.append(canonical_role(role))
    if visible is not None:
        assignments.append("visible=?")
        parameters.append(int(visible))
    if assignments:
        parameters.append(source_id)
        user_conn.execute(
            f"UPDATE files_sources SET {', '.join(assignments)} WHERE source_id=?",
            parameters,
        )
        if commit:
            user_conn.commit()
    return get_source(user_conn, source_id)


# --- Module projection (folder-roles, §4.2) -------------------------------
# A module (e.g. Danbooru) keeps its own storage as the source of truth and
# *publishes* its managed folders into this shared browse-list with a role, so
# the base can show them without ever reading the module's private tables. The
# dependency points module -> base, never the reverse.

def upsert_module_source(
    user_conn: sqlite3.Connection,
    path: str | Path,
    display_name: str | None,
    role: str,
) -> str:
    """Publish (create or re-role) a module-managed folder in the shared list."""
    resolved = Path(path).expanduser().resolve(strict=False)
    source_id = deterministic_source_id(resolved)
    name = display_name.strip() if display_name and display_name.strip() else resolved.name
    existing = get_source(user_conn, source_id)
    if existing is None:
        user_conn.execute(
            "INSERT INTO files_sources (source_id, path, display_name, role, visible) VALUES (?, ?, ?, ?, 1)",
            (source_id, str(resolved), name, canonical_role(role)),
        )
    else:
        user_conn.execute(
            "UPDATE files_sources SET role = ? WHERE source_id = ?",
            (canonical_role(role), source_id),
        )
    user_conn.commit()
    return source_id


def remove_source_by_path(user_conn: sqlite3.Connection, path: str | Path) -> bool:
    """Remove a shared-list entry by its path (used when a module drops a folder)."""
    resolved = Path(path).expanduser().resolve(strict=False)
    return remove_source(user_conn, deterministic_source_id(resolved))


def reconcile_module_sources(
    user_conn: sqlite3.Connection,
    role: str,
    folders: list[tuple[str, str | None]],
) -> None:
    """Make the shared list's ``role`` rows exactly match ``folders``.

    Publishes each (path, display_name) and prunes any ``role`` row no longer
    present, so a missed hook self-heals on the next startup reconcile.
    """
    wanted = {upsert_module_source(user_conn, path, name, role) for path, name in folders}
    existing = user_conn.execute(
        "SELECT source_id FROM files_sources WHERE role IN (?, ?)",
        (canonical_role(role), "base" if canonical_role(role) == "files" else canonical_role(role)),
    ).fetchall()
    for row in existing:
        if row["source_id"] not in wanted:
            user_conn.execute("DELETE FROM files_sources WHERE source_id = ?", (row["source_id"],))
    user_conn.commit()
