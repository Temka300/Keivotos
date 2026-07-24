"""Local lookups for Danbooru post references (parents, siblings, wiki examples).

Extracted verbatim from ``core.py``. Given Danbooru post IDs, these resolve which
of them exist in the local library so the UI can show a real thumbnail instead of
a remote placeholder — the "no hotlinking" contract. No ``core`` import.
"""
from __future__ import annotations

from typing import Any

from models import RelatedImageInfo
from modules.danbooru.client import DANBOORU_POST_URL_PREFIX
from services.value_helpers import unique_ints
from thumbnails import thumbnail_cache_token


def related_info_from_row(row: dict[str, Any]) -> RelatedImageInfo:
    return RelatedImageInfo(
        danbooru_post_id=row["danbooru_post_id"],
        local_post_id=row["local_post_id"],
        file_id=row["file_id"],
        thumbnail_token=row["local_md5"] or thumbnail_cache_token(row["path"]),
        filename=row["filename"],
        folder=row["folder"],
        ext=row["ext"],
        width=row["width"],
        height=row["height"],
        score=row["score"],
        rating=row["rating"],
        post_url=row["post_url"] or f"{DANBOORU_POST_URL_PREFIX}{row['danbooru_post_id']}",
        created_at=row["created_at"],
    )


def related_infos_for_danbooru_ids(
    conn,
    danbooru_ids: list[int],
) -> dict[int, RelatedImageInfo]:
    ids = unique_ints(danbooru_ids)
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""SELECT p.id as local_post_id, p.danbooru_post_id, p.post_url,
                  p.created_at, p.width, p.height, p.score, p.rating,
                  f.id as file_id, f.name as filename, f.folder, f.ext, f.path, f.local_md5
           FROM posts p
           JOIN files f ON f.id = p.file_id
           WHERE p.danbooru_post_id IN ({placeholders})""",
        ids,
    ).fetchall()
    return {row["danbooru_post_id"]: related_info_from_row(row) for row in rows}


def related_info_for_id(
    danbooru_post_id: int,
    local_infos: dict[int, RelatedImageInfo],
) -> RelatedImageInfo:
    local_info = local_infos.get(danbooru_post_id)
    if local_info:
        return local_info
    return RelatedImageInfo(
        danbooru_post_id=danbooru_post_id,
        post_url=f"{DANBOORU_POST_URL_PREFIX}{danbooru_post_id}",
    )
