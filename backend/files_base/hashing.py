"""Lazy content hashing and duplicate detection for the Files base (V1.1.0).

Contract rules (SUITE_MODULE_CONTRACT.md sections 4.1 and 10):
- Hashing is on-demand, never a per-file tax. Browsing needs no hash.
- Duplicates can only share an exact byte-size, so only size-colliding files
  are ever read and hashed; everything else is skipped entirely.
- Dedup is a base capability: only the base sees across every source/folder.
- MD5 is the content key, matching Danbooru's existing end-to-end convention.

Isolated: no Danbooru or ``core`` imports.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from files_base.index import FileEntry, _row_to_entry


_CHUNK_SIZE = 1024 * 1024


def _md5_of_file(path: Path) -> str | None:
    digest = hashlib.md5()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK_SIZE):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def ensure_index_hash(connection: sqlite3.Connection, path: Path) -> str | None:
    """Return a file's content hash, computing it on demand (the annotate moment).

    Reuses an already-indexed hash when present; otherwise reads the file once,
    stores the digest back on its index row when that row exists (so duplicate
    detection benefits too), and returns it. Returns ``None`` if unreadable.
    """
    row = connection.execute(
        "SELECT id, content_hash FROM files_index WHERE path = ?", (str(path),)
    ).fetchone()
    if row is not None and row["content_hash"]:
        return row["content_hash"]
    digest = _md5_of_file(path)
    if digest is None:
        return None
    if row is not None:
        connection.execute(
            "UPDATE files_index SET content_hash = ?, hashed_at = ? WHERE id = ?",
            (digest, datetime.now(timezone.utc).isoformat(), row["id"]),
        )
        connection.commit()
    return digest


def hash_candidate_ids(connection: sqlite3.Connection, source_id: str | None = None) -> list[int]:
    """Ids of unhashed files whose size collides with another file's size.

    Size groups are computed across ALL sources (a duplicate can span sources);
    ``source_id`` only narrows which files get hashed now.
    """
    clauses = [
        "f.is_dir = 0",
        "f.available = 1",
        "f.content_hash IS NULL",
        "f.size IS NOT NULL",
    ]
    params: list[object] = []
    if source_id is not None:
        clauses.append("f.source_id = ?")
        params.append(source_id)
    rows = connection.execute(
        f"""SELECT f.id FROM files_index f
             WHERE {' AND '.join(clauses)}
               AND f.size IN (
                   SELECT size FROM files_index
                    WHERE is_dir = 0 AND available = 1 AND size IS NOT NULL
                    GROUP BY size HAVING COUNT(*) > 1
               )
             ORDER BY f.size DESC, f.id ASC""",
        params,
    ).fetchall()
    return [row["id"] for row in rows]


def compute_missing_hashes(
    connection: sqlite3.Connection,
    source_id: str | None = None,
    limit: int = 500,
) -> dict[str, int]:
    """Hash up to ``limit`` size-colliding files that lack a content hash."""
    hashed = failed = 0
    now = datetime.now(timezone.utc).isoformat()
    candidates = hash_candidate_ids(connection, source_id)
    remaining = max(len(candidates) - limit, 0)
    for file_id in candidates[:limit]:
        row = connection.execute(
            "SELECT path FROM files_index WHERE id = ?", (file_id,)
        ).fetchone()
        if row is None:
            continue
        digest = _md5_of_file(Path(row["path"]))
        if digest is None:
            failed += 1
            continue
        connection.execute(
            "UPDATE files_index SET content_hash = ?, hashed_at = ? WHERE id = ?",
            (digest, now, file_id),
        )
        hashed += 1
    connection.commit()
    return {"hashed": hashed, "failed": failed, "remaining": remaining}


def find_duplicates(connection: sqlite3.Connection) -> list[list[FileEntry]]:
    """Groups of available files sharing the same content hash, largest first."""
    rows = connection.execute(
        """SELECT * FROM files_index
            WHERE is_dir = 0 AND available = 1 AND content_hash IS NOT NULL
              AND content_hash IN (
                  SELECT content_hash FROM files_index
                   WHERE is_dir = 0 AND available = 1 AND content_hash IS NOT NULL
                   GROUP BY content_hash HAVING COUNT(*) > 1
              )
            ORDER BY size DESC, content_hash ASC, path ASC"""
    ).fetchall()
    groups: dict[str, list[FileEntry]] = {}
    order: list[str] = []
    for row in rows:
        key = row["content_hash"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(_row_to_entry(row))
    return [groups[key] for key in order]
