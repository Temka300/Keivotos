"""Local profile artwork selection (avatar and banner candidates).

Extracted verbatim from ``core.py``'s Stats section. No inbound dependency on
``core``; ``thumbnails`` owns the cache token helper it needs.
"""
from __future__ import annotations

from typing import Any

from thumbnails import thumbnail_cache_token


def profile_asset(conn, folder_names: list[str], ratio_clause: str) -> dict[str, Any] | None:
    names = [name.casefold() for name in folder_names]
    placeholders = ",".join("?" for _ in names)
    image_exts = "'jpg','jpeg','png','webp','gif'"
    base_where = (
        f"LOWER(COALESCE(f.folder, '')) IN ({placeholders}) "
        f"AND LOWER(COALESCE(f.ext, '')) IN ({image_exts})"
    )

    for clause in (ratio_clause, ""):
        where = base_where
        if clause:
            where = f"{where} AND {clause}"
        row = conn.execute(
            f"""SELECT f.id as file_id, f.path, f.local_md5
                FROM files f
                LEFT JOIN posts p ON p.file_id = f.id
                WHERE {where}
                ORDER BY COALESCE(p.score, -999999) DESC,
                         COALESCE(f.downloaded_at, '') DESC,
                         f.name ASC
                LIMIT 1""",
            names,
        ).fetchone()
        if row:
            return row
    return None


def profile_asset_token(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    return row["local_md5"] or thumbnail_cache_token(row["path"])
