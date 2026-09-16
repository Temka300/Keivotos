"""Local lookups for Danbooru post references (parents, siblings, wiki examples).

Extracted verbatim from ``core.py``. Given Danbooru post IDs, these resolve which
of them exist in the local library so the UI can show a real thumbnail instead of
a remote placeholder — the "no hotlinking" contract. No ``core`` import.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException

from modules.danbooru.models import ImageRelations, RelatedImageInfo
from modules.danbooru.client import (
    DANBOORU_POST_URL_PREFIX,
    danbooru_json,
    normalize_danbooru_post_payload,
)
from services.value_helpers import int_or_none, unique_ints
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


def relation_post_id(value: Any) -> int | None:
    if isinstance(value, dict):
        return int_or_none(value.get("id"))
    return int_or_none(value)


def child_ids_from_value(value: Any) -> list[int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return unique_ints([relation_post_id(child) for child in value])


def relation_ids_from_raw_json(raw_json: str | None) -> tuple[int | None, list[int], bool]:
    if not raw_json:
        return None, [], False
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return None, [], False
    post = payload.get("post") if isinstance(payload, dict) else None
    if not isinstance(post, dict):
        post = payload if isinstance(payload, dict) else {}

    parent_id = int_or_none(post.get("parent_id")) or relation_post_id(post.get("parent"))
    child_ids = child_ids_from_value(post.get("children"))
    has_metadata = parent_id is not None or bool(child_ids) or bool(post.get("has_children"))
    return parent_id, child_ids, has_metadata


def danbooru_child_search(parent_id: int) -> list[dict[str, Any]]:
    data = danbooru_json(
        "/posts.json",
        {
            "tags": f"parent:{parent_id}",
            "limit": 200,
            "only": "id,parent_id,has_children,children",
        },
    )
    if not isinstance(data, list):
        return []
    return [post for post in data if isinstance(post, dict)]


def update_relation_columns(
    conn,
    danbooru_post_id: int,
    parent_id: int | None,
    has_children: bool | None,
    child_ids: list[int] | None = None,
    *,
    update_parent: bool = True,
) -> None:
    if update_parent and parent_id == danbooru_post_id:
        parent_id = None
    if child_ids is not None:
        child_ids = [child_id for child_id in unique_ints(child_ids) if child_id != danbooru_post_id]

    assignments: list[str] = []
    params: list[Any] = []
    if update_parent:
        assignments.append("parent_id=?")
        params.append(parent_id)

    if has_children is not None:
        assignments.append("has_children=?")
        params.append(1 if has_children else 0)
    if child_ids is not None:
        assignments.append("child_ids_json=?")
        params.append(json.dumps(unique_ints(child_ids)) if child_ids else None)

    params.append(danbooru_post_id)
    conn.execute(
        f"UPDATE posts SET {', '.join(assignments)} WHERE danbooru_post_id=?",
        params,
    )


def refresh_relation_cache(conn, danbooru_post_id: int) -> None:
    post = normalize_danbooru_post_payload(
        danbooru_json(
            f"/posts/{danbooru_post_id}.json",
            {"only": "id,parent_id,has_children,children"},
        )
    )
    if not post:
        raise HTTPException(404, "Danbooru post not found")

    parent_id = int_or_none(post.get("parent_id")) or relation_post_id(post.get("parent"))
    if parent_id == danbooru_post_id:
        parent_id = None
    child_ids = child_ids_from_value(post.get("children"))
    if post.get("has_children") and not child_ids:
        child_ids = unique_ints([relation_post_id(child) for child in danbooru_child_search(danbooru_post_id)])
    child_ids = [child_id for child_id in child_ids if child_id != danbooru_post_id]
    has_children = bool(post.get("has_children") or child_ids)
    update_relation_columns(conn, danbooru_post_id, parent_id, has_children, child_ids)

    if child_ids:
        for child in danbooru_child_search(danbooru_post_id):
            child_id = relation_post_id(child)
            if child_id is None or child_id == danbooru_post_id:
                continue
            update_relation_columns(
                conn,
                child_id,
                danbooru_post_id,
                bool(child.get("has_children")),
                child_ids_from_value(child.get("children")),
            )

    if parent_id is not None:
        sibling_posts = danbooru_child_search(parent_id)
        sibling_ids = unique_ints([relation_post_id(sibling) for sibling in sibling_posts])
        sibling_ids = [sibling_id for sibling_id in sibling_ids if sibling_id != parent_id]
        update_relation_columns(
            conn,
            parent_id,
            None,
            bool(sibling_ids),
            sibling_ids,
            update_parent=False,
        )
        for sibling in sibling_posts:
            sibling_id = relation_post_id(sibling)
            if sibling_id is None or sibling_id == parent_id:
                continue
            update_relation_columns(
                conn,
                sibling_id,
                parent_id,
                bool(sibling.get("has_children")),
                child_ids_from_value(sibling.get("children")),
            )


def local_child_ids_for_parent(conn, parent_id: int, current_danbooru_id: int | None = None) -> list[int]:
    rows = conn.execute(
        """SELECT danbooru_post_id
           FROM posts
           WHERE parent_id=? AND danbooru_post_id IS NOT NULL""",
        (parent_id,),
    ).fetchall()
    ids = [int_or_none(row["danbooru_post_id"]) for row in rows]
    return [post_id for post_id in unique_ints(ids) if post_id != current_danbooru_id]


def relation_ids_for_post_row(row: dict[str, Any]) -> tuple[int | None, list[int], bool]:
    raw_parent_id, raw_child_ids, raw_has_metadata = relation_ids_from_raw_json(row.get("raw_json"))
    parent_id = int_or_none(row.get("parent_id")) or raw_parent_id
    child_ids = unique_ints([
        *child_ids_from_value(row.get("child_ids_json")),
        *raw_child_ids,
    ])
    has_metadata = parent_id is not None or bool(child_ids) or bool(row.get("has_children")) or raw_has_metadata
    return parent_id, child_ids, has_metadata


def build_image_relations(conn, row: dict[str, Any]) -> ImageRelations:
    current_danbooru_id = int_or_none(row.get("danbooru_post_id"))
    if current_danbooru_id is None:
        return ImageRelations()

    parent_id, child_ids, has_metadata = relation_ids_for_post_row(row)
    child_ids = unique_ints([
        *child_ids,
        *local_child_ids_for_parent(conn, current_danbooru_id, current_danbooru_id),
    ])
    child_ids = [post_id for post_id in child_ids if post_id != current_danbooru_id]

    sibling_ids: list[int] = []
    if parent_id is not None:
        sibling_ids.extend(local_child_ids_for_parent(conn, parent_id, current_danbooru_id))
        parent_row = conn.execute(
            "SELECT parent_id, has_children, child_ids_json, raw_json FROM posts WHERE danbooru_post_id=?",
            (parent_id,),
        ).fetchone()
        if parent_row:
            _, parent_child_ids, parent_has_metadata = relation_ids_for_post_row(parent_row)
            sibling_ids.extend(parent_child_ids)
            has_metadata = has_metadata or parent_has_metadata
    sibling_ids = [post_id for post_id in unique_ints(sibling_ids) if post_id != current_danbooru_id]

    all_relation_ids = unique_ints([
        parent_id,
        *child_ids,
        *sibling_ids,
    ])
    local_infos = related_infos_for_danbooru_ids(conn, all_relation_ids)

    return ImageRelations(
        parent=related_info_for_id(parent_id, local_infos) if parent_id is not None else None,
        siblings=[related_info_for_id(post_id, local_infos) for post_id in sibling_ids],
        children=[related_info_for_id(post_id, local_infos) for post_id in child_ids],
        has_metadata=has_metadata,
    )
