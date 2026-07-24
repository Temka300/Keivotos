"""Collection queries and preview construction.

Extracted verbatim from ``core.py``'s Collections section. This module has no
inbound dependency on ``core``: every helper it needs already has a real owner
(``models``, ``services.query_helpers``, ``thumbnails``), so it imports them
directly. ``core`` imports these names back and re-exports them, which keeps the
routers that still wildcard-import it working unchanged.
"""
from __future__ import annotations

from models import CollectionInfo, CollectionPreviewItem
from services.query_helpers import user_file_match
from thumbnails import thumbnail_cache_token


def collection_preview_items_from_rows(rows) -> list[CollectionPreviewItem]:
    items: list[CollectionPreviewItem] = []
    for row in rows:
        file_id = row["file_id"]
        if file_id is None:
            continue
        path = row["path"]
        local_md5 = row["local_md5"]
        items.append(
            CollectionPreviewItem(
                file_id=file_id,
                thumbnail_token=(local_md5 or thumbnail_cache_token(path)) if path else local_md5,
                filename=row["filename"],
                ext=row["ext"],
                width=row["width"],
                height=row["height"],
            )
        )
    return items


def load_collection_info(conn, collection_id: int) -> CollectionInfo | None:
    row = conn.execute(
        f"""SELECT c.id, c.name, c.description, c.created_at, c.pinned_at,
                  COUNT(DISTINCT COALESCE(f.id, ci.file_id)) as image_count
           FROM collections c
           LEFT JOIN collection_items ci ON ci.collection_id = c.id
           LEFT JOIN datadb.files f ON {user_file_match("ci")}
           WHERE c.id=?
           GROUP BY c.id""",
        (collection_id,),
    ).fetchone()
    if not row:
        return None
    previews = conn.execute(
        f"""SELECT COALESCE(f.id, ci.file_id) as file_id,
                  f.path as path,
                  COALESCE(f.local_md5, ci.local_md5) as local_md5,
                  f.name as filename,
                  f.ext as ext,
                  p.width as width,
                  p.height as height
            FROM collection_items ci
            LEFT JOIN datadb.files f ON {user_file_match("ci")}
            LEFT JOIN datadb.posts p ON p.file_id = f.id
            WHERE ci.collection_id=?
            ORDER BY CASE WHEN ci.pinned_at IS NULL THEN 1 ELSE 0 END,
                     ci.pinned_at DESC,
                     ci.added_at DESC
            LIMIT 4""",
        (collection_id,),
    ).fetchall()
    preview_items = collection_preview_items_from_rows(previews)
    return CollectionInfo(
        **row,
        preview_ids=[item.file_id for item in preview_items],
        preview_items=preview_items,
    )
