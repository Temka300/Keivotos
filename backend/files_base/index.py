"""Isolated file-index engine for the Files base (V1.1.0).

Responsibilities:
- open the disposable ``files.sqlite`` index (WAL);
- scan a source folder into the index using only cheap ``stat`` facts — no file
  contents are read and no content hash is computed here (hashing is lazy and
  lives in a later slice);
- answer directory-listing and filename-search queries.

Design constraints (SUITE_MODULE_CONTRACT.md):
- No import of Danbooru modules or ``core``; this engine is fully standalone.
- Files that disappear are marked ``available = 0`` (missing != deleted), never
  removed, so user data referencing them survives a move or an unplugged drive.
- The engine authors no metadata; it records what the disk says and nothing more.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Iterable

from files_base.schema import ensure_files_schema


# Keivotos-generated directories that live inside a user's folder but must never
# be indexed as browsable content (currently the attachment byte store).
EXCLUDED_DIR_NAMES = {".keivotos"}


@dataclass(frozen=True)
class FileEntry:
    """One indexed filesystem entry (a file or a directory)."""

    source_id: str
    path: str
    relative_path: str
    parent: str
    name: str
    ext: str | None
    is_dir: bool
    size: int | None
    mtime: int | None
    content_hash: str | None
    available: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_entry(row: sqlite3.Row) -> FileEntry:
    return FileEntry(
        source_id=row["source_id"],
        path=row["path"],
        relative_path=row["relative_path"],
        parent=row["parent"],
        name=row["name"],
        ext=row["ext"],
        is_dir=bool(row["is_dir"]),
        size=row["size"],
        mtime=row["mtime"],
        content_hash=row["content_hash"],
        available=bool(row["available"]),
    )


def _escape_like(term: str) -> str:
    """Escape LIKE wildcards so user input is matched literally."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@contextmanager
def open_index(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Open the file index at ``db_path``, ensuring its schema and WAL mode."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        ensure_files_schema(connection)
        yield connection
    finally:
        connection.close()


def scan_source(
    connection: sqlite3.Connection,
    source_id: str,
    root: Path,
    *,
    excluded_roots: Iterable[Path] = (),
) -> dict[str, int]:
    """Index every file and directory beneath ``root`` for ``source_id``.

    Records only cheap ``stat`` facts. Entries not seen during this scan are
    marked unavailable rather than deleted. Registered descendant roots are
    indexed by their own source; their directory entry remains visible in the
    parent, but this scan never descends into them. Returns a small counts
    summary.
    """
    root = Path(root).expanduser().resolve(strict=False)
    excluded = {
        os.path.normcase(str(Path(path).expanduser().resolve(strict=False)))
        for path in excluded_roots
        if Path(path).expanduser().resolve(strict=False) != root
    }
    # Reset availability inside the scan transaction, then mark observed rows.
    # Wall clocks can repeat or move backwards, so timestamps cannot identify
    # which rows this scan visited. Keep their last-seen timestamps intact.
    connection.execute(
        "UPDATE files_index SET available = 0 WHERE source_id = ?", (source_id,)
    )
    scan_token = _now()
    added = updated = directories = files = 0

    def upsert(path: Path, is_dir: bool) -> None:
        nonlocal added, updated, directories, files
        try:
            stat_result = path.stat()
        except OSError:
            return
        relative = path.relative_to(root).as_posix()
        parent = os.path.dirname(relative)
        name = path.name
        ext = "" if is_dir else path.suffix.lower().lstrip(".")
        size = None if is_dir else int(stat_result.st_size)
        mtime = int(stat_result.st_mtime)
        existing = connection.execute(
            "SELECT id FROM files_index WHERE path = ?", (str(path),)
        ).fetchone()
        if existing is None:
            connection.execute(
                """INSERT INTO files_index
                       (source_id, path, relative_path, parent, name, ext, is_dir,
                        size, mtime, indexed_at, seen_at, available)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (source_id, str(path), relative, parent, name, ext, int(is_dir),
                 size, mtime, scan_token, scan_token),
            )
            added += 1
        else:
            connection.execute(
                """UPDATE files_index
                       SET source_id = ?, relative_path = ?, parent = ?, name = ?,
                           ext = ?, is_dir = ?, size = ?, mtime = ?, seen_at = ?,
                           available = 1
                     WHERE id = ?""",
                (source_id, relative, parent, name, ext, int(is_dir), size, mtime,
                 scan_token, existing["id"]),
            )
            updated += 1
        if is_dir:
            directories += 1
        else:
            files += 1

    if root.is_dir():
        for current_dir, dir_names, file_names in os.walk(root):
            current = Path(current_dir)
            descend_into: list[str] = []
            for dir_name in sorted(dir_names):
                if dir_name in EXCLUDED_DIR_NAMES:
                    continue  # Keivotos-generated storage; never index or descend.
                directory = current / dir_name
                upsert(directory, is_dir=True)
                resolved = os.path.normcase(
                    str(directory.expanduser().resolve(strict=False))
                )
                if resolved not in excluded:
                    descend_into.append(dir_name)
            dir_names[:] = descend_into
            for file_name in sorted(file_names):
                upsert(current / file_name, is_dir=False)

    unavailable = connection.execute(
        "SELECT COUNT(*) FROM files_index WHERE source_id = ? AND available = 0",
        (source_id,),
    ).fetchone()[0]
    connection.commit()
    return {
        "added": added,
        "updated": updated,
        "files": files,
        "directories": directories,
        "unavailable": max(unavailable, 0),
    }


def source_is_indexed(connection: sqlite3.Connection, source_id: str) -> bool:
    """Whether this source has ever been scanned into the index."""
    row = connection.execute(
        "SELECT 1 FROM files_index WHERE source_id = ? LIMIT 1", (source_id,)
    ).fetchone()
    return row is not None


def source_entry_count(connection: sqlite3.Connection, source_id: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM files_index WHERE source_id=? AND is_dir=0",
        (source_id,),
    ).fetchone()
    return int(row["count"] if row is not None else 0)


def drop_source(connection: sqlite3.Connection, source_id: str) -> int:
    """Remove all index rows for a source (un-index only; disk is untouched)."""
    removed = connection.execute(
        "DELETE FROM files_index WHERE source_id = ?", (source_id,)
    ).rowcount
    connection.commit()
    return max(removed, 0)


def list_directory(
    connection: sqlite3.Connection,
    source_id: str,
    parent: str = "",
    include_unavailable: bool = False,
) -> list[FileEntry]:
    """List the direct children of ``parent`` within ``source_id``.

    Directories are returned before files; both are name-sorted case-insensitively.
    """
    clauses = ["source_id = ?", "parent = ?"]
    params: list[object] = [source_id, parent]
    if not include_unavailable:
        clauses.append("available = 1")
    query = (
        "SELECT * FROM files_index WHERE "
        + " AND ".join(clauses)
        + " ORDER BY is_dir DESC, name COLLATE NOCASE ASC"
    )
    return [_row_to_entry(row) for row in connection.execute(query, params)]


def search_by_name(
    connection: sqlite3.Connection,
    term: str,
    source_id: str | None = None,
    source_ids: Iterable[str] | None = None,
    limit: int = 200,
    include_unavailable: bool = False,
) -> list[FileEntry]:
    """Find entries whose name contains ``term`` (case-insensitive substring)."""
    clauses = ["name LIKE ? ESCAPE '\\'"]
    params: list[object] = [f"%{_escape_like(term)}%"]
    if source_id is not None and source_ids is not None:
        raise ValueError("Pass source_id or source_ids, not both")
    if source_id is not None:
        clauses.append("source_id = ?")
        params.append(source_id)
    elif source_ids is not None:
        ids = list(dict.fromkeys(source_ids))
        if not ids:
            return []
        clauses.append(f"source_id IN ({','.join('?' for _ in ids)})")
        params.extend(ids)
    if not include_unavailable:
        clauses.append("available = 1")
    query = (
        "SELECT * FROM files_index WHERE "
        + " AND ".join(clauses)
        + " ORDER BY is_dir DESC, name COLLATE NOCASE ASC LIMIT ?"
    )
    params.append(int(limit))
    return [_row_to_entry(row) for row in connection.execute(query, params)]
