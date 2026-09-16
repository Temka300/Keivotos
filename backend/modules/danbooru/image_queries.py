"""Resolving a file's durable identity and building its API summary.

Moved verbatim from ``core.py``. Identity is the file's stable path/MD5, not a
row id, which is what lets favorites and collections survive an index rebuild.
No ``core`` import.
"""
from __future__ import annotations

from typing import Any, Iterable

from fastapi import HTTPException

from config import USER_DB_PATH
from database import get_data_db
from models import ImageSummary
from modules.danbooru.query_helpers import user_file_match
from thumbnails import thumbnail_cache_token


def get_file_identity(file_id: int) -> dict[str, Any]:
    with get_data_db() as conn:
        row = conn.execute(
            "SELECT id as file_id, path, local_md5 FROM files WHERE id=?",
            (file_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "File not found")
    return row


def get_post_file_identity(post_id: int) -> dict[str, Any]:
    with get_data_db() as conn:
        row = conn.execute(
            """SELECT p.id as id, f.id as file_id, f.path, f.local_md5
               FROM posts p
               JOIN files f ON f.id = p.file_id
               WHERE p.id=?""",
            (post_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Image not found")
    return row


def favorite_meta_by_file(file_ids: Iterable[int] | None = None) -> dict[int, dict[str, str | None]]:
    requested_ids = sorted({int(file_id) for file_id in file_ids}) if file_ids is not None else None
    if requested_ids == []:
        return {}
    file_filter = ""
    params: list[Any] = []
    if requested_ids is not None:
        file_filter = f"WHERE f.id IN ({','.join('?' for _ in requested_ids)})"
        params.extend(requested_ids)
    with get_data_db() as conn:
        conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))
        rows = conn.execute(
            f"""SELECT f.id as file_id,
                       MAX(fav.added_at) as added_at,
                       MAX(fav.pinned_at) as pinned_at
                FROM files f
                JOIN userdb.favorites fav ON {user_file_match("fav")}
                {file_filter}
                GROUP BY f.id"""
            , params
        ).fetchall()
    return {
        r["file_id"]: {
            "added_at": r["added_at"],
            "pinned_at": r["pinned_at"],
        }
        for r in rows
    }


def image_summary_from_row(
    row: dict[str, Any],
    fav_file_ids: set[int] | None = None,
    fav_meta_by_file: dict[int, dict[str, str | None]] | None = None,
) -> ImageSummary:
    data = dict(row)
    source_path = data.pop("path")
    favorite_added_at = data.pop("favorite_added_at", None)
    favorite_pinned_at = data.pop("favorite_pinned_at", None)
    data["thumbnail_token"] = data.pop("local_md5") or thumbnail_cache_token(source_path)
    fav_file_ids = fav_file_ids or set()
    fav_meta_by_file = fav_meta_by_file or {}
    fav_meta = fav_meta_by_file.get(row["file_id"])
    return ImageSummary(
        **data,
        is_favorite=row["file_id"] in fav_file_ids or fav_meta is not None,
        favorite_added_at=favorite_added_at or (fav_meta["added_at"] if fav_meta else None),
        favorite_pinned_at=favorite_pinned_at or (fav_meta["pinned_at"] if fav_meta else None),
    )
