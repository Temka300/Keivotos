from __future__ import annotations

from fastapi import APIRouter
from core import *  # shared query, database, and media helpers

router = APIRouter()


@router.post("/api/collections/memberships")
def collection_memberships(data: CollectionMembershipRequest):
    file_ids = list(dict.fromkeys(data.file_ids))
    memberships = {str(file_id): [] for file_id in file_ids}
    if not file_ids:
        return {"memberships": memberships}
    placeholders = ",".join("?" for _ in file_ids)
    with get_user_db() as conn:
        conn.execute("ATTACH DATABASE ? AS datadb", (str(DATA_DB_PATH),))
        try:
            rows = conn.execute(
                f"""SELECT DISTINCT f.id as file_id, ci.collection_id
                    FROM collection_items ci
                    JOIN datadb.files f ON {user_file_match("ci")}
                    WHERE f.id IN ({placeholders})
                    ORDER BY ci.collection_id""",
                file_ids,
            ).fetchall()
        finally:
            conn.execute("DETACH DATABASE datadb")
    for row in rows:
        memberships[str(row["file_id"])].append(row["collection_id"])
    return {"memberships": memberships}


@router.get("/api/collections", response_model=list[CollectionInfo])
def list_collections():
    with get_user_db() as conn:
        conn.execute("ATTACH DATABASE ? AS datadb", (str(DATA_DB_PATH),))
        try:
            rows = conn.execute(
                f"""SELECT c.id, c.name, c.description, c.created_at, c.pinned_at,
                          COUNT(DISTINCT COALESCE(f.id, ci.file_id)) as image_count
                   FROM collections c
                   LEFT JOIN collection_items ci ON ci.collection_id = c.id
                   LEFT JOIN datadb.files f ON {user_file_match("ci")}
                   GROUP BY c.id
                   ORDER BY CASE WHEN c.pinned_at IS NULL THEN 1 ELSE 0 END,
                            c.pinned_at DESC,
                            c.created_at DESC"""
            ).fetchall()
            preview_rows = conn.execute(
                f"""WITH ranked_previews AS (
                       SELECT ci.collection_id,
                              COALESCE(f.id, ci.file_id) as file_id,
                              f.path as path,
                              COALESCE(f.local_md5, ci.local_md5) as local_md5,
                              f.name as filename,
                              f.ext as ext,
                              p.width as width,
                              p.height as height,
                              ROW_NUMBER() OVER (
                                  PARTITION BY ci.collection_id
                                  ORDER BY CASE WHEN ci.pinned_at IS NULL THEN 1 ELSE 0 END,
                                           ci.pinned_at DESC,
                                           ci.added_at DESC
                              ) as preview_rank
                       FROM collection_items ci
                       LEFT JOIN datadb.files f ON {user_file_match("ci")}
                       LEFT JOIN datadb.posts p ON p.file_id = f.id
                   )
                   SELECT * FROM ranked_previews
                   WHERE preview_rank <= 4
                   ORDER BY collection_id, preview_rank"""
            ).fetchall()
            previews_by_collection: dict[int, list] = {}
            for preview_row in preview_rows:
                previews_by_collection.setdefault(preview_row["collection_id"], []).append(preview_row)
            result = []
            for r in rows:
                preview_items = collection_preview_items_from_rows(previews_by_collection.get(r["id"], []))
                result.append(
                    CollectionInfo(
                        **r,
                        preview_ids=[item.file_id for item in preview_items],
                        preview_items=preview_items,
                    )
                )
        finally:
            conn.execute("DETACH DATABASE datadb")
    return result


@router.post("/api/collections", response_model=CollectionInfo)
def create_collection(data: CollectionCreate):
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Collection name is required")
    description = data.description.strip()
    with get_user_db() as conn:
        cur = conn.execute(
            "INSERT INTO collections (name, description) VALUES (?, ?)",
            (name, description),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM collections WHERE id=?", (cur.lastrowid,)).fetchone()
    return CollectionInfo(**row, image_count=0, preview_ids=[], preview_items=[])


@router.put("/api/collections/{collection_id}", response_model=CollectionInfo)
def update_collection(collection_id: int, data: CollectionUpdate):
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Collection name is required")
    description = data.description.strip()
    with get_user_db() as conn:
        existing = conn.execute("SELECT id FROM collections WHERE id=?", (collection_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Collection not found")
        conn.execute(
            "UPDATE collections SET name=?, description=? WHERE id=?",
            (name, description, collection_id),
        )
        conn.commit()
        conn.execute("ATTACH DATABASE ? AS datadb", (str(DATA_DB_PATH),))
        try:
            updated = load_collection_info(conn, collection_id)
        finally:
            conn.execute("DETACH DATABASE datadb")
    if not updated:
        raise HTTPException(404, "Collection not found")
    return updated


@router.post("/api/collections/{collection_id}/pin")
def toggle_collection_pin(collection_id: int):
    with get_user_db() as conn:
        existing = conn.execute(
            "SELECT pinned_at FROM collections WHERE id=?",
            (collection_id,),
        ).fetchone()
        if not existing:
            raise HTTPException(404, "Collection not found")
        if existing["pinned_at"]:
            conn.execute("UPDATE collections SET pinned_at=NULL WHERE id=?", (collection_id,))
            conn.commit()
            return {"status": "unpinned", "pinned_at": None}
        conn.execute("UPDATE collections SET pinned_at=datetime('now') WHERE id=?", (collection_id,))
        conn.commit()
        row = conn.execute("SELECT pinned_at FROM collections WHERE id=?", (collection_id,)).fetchone()
        return {"status": "pinned", "pinned_at": row["pinned_at"] if row else None}


@router.delete("/api/collections/{collection_id}")
def delete_collection(collection_id: int):
    with get_user_db() as conn:
        conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))
        conn.commit()
    return {"status": "deleted"}


@router.post("/api/collections/{collection_id}/images/{file_id}/pin")
def toggle_collection_image_pin(collection_id: int, file_id: int):
    file_row = get_file_identity(file_id)
    with get_user_db() as conn:
        existing = conn.execute(
            f"""SELECT pinned_at FROM collection_items
                WHERE collection_id=? AND {user_file_lookup_sql()}""",
            [collection_id, *user_file_lookup_params(file_row)],
        ).fetchone()
        if not existing:
            raise HTTPException(400, "Only images in this collection can be pinned")
        if existing["pinned_at"]:
            conn.execute(
                f"""UPDATE collection_items SET pinned_at=NULL
                    WHERE collection_id=? AND {user_file_lookup_sql()}""",
                [collection_id, *user_file_lookup_params(file_row)],
            )
            conn.commit()
            return {"status": "unpinned", "pinned_at": None}
        conn.execute(
            f"""UPDATE collection_items SET pinned_at=datetime('now')
                WHERE collection_id=? AND {user_file_lookup_sql()}""",
            [collection_id, *user_file_lookup_params(file_row)],
        )
        conn.commit()
        row = conn.execute(
            f"""SELECT pinned_at FROM collection_items
                WHERE collection_id=? AND {user_file_lookup_sql()}""",
            [collection_id, *user_file_lookup_params(file_row)],
        ).fetchone()
        return {"status": "pinned", "pinned_at": row["pinned_at"] if row else None}


@router.put("/api/collections/{collection_id}/images")
def update_collection_images(collection_id: int, data: CollectionItemsUpdate):
    added_at_by_file: dict[str, str | None] = {}
    with get_user_db() as conn:
        collection = conn.execute("SELECT id FROM collections WHERE id=?", (collection_id,)).fetchone()
        if not collection:
            raise HTTPException(404, "Collection not found")
        if data.action == "add":
            for fid in data.file_ids:
                file_row = get_file_identity(fid)
                conn.execute(
                    """INSERT OR IGNORE INTO collection_items
                       (collection_id, file_id, file_path, local_md5)
                       VALUES (?, ?, ?, ?)""",
                    (collection_id, fid, file_row["path"], file_row["local_md5"]),
                )
                row = conn.execute(
                    f"""SELECT added_at FROM collection_items
                        WHERE collection_id=? AND {user_file_lookup_sql()}""",
                    [collection_id, *user_file_lookup_params(file_row)],
                ).fetchone()
                added_at_by_file[str(fid)] = row["added_at"] if row else None
        elif data.action == "remove":
            for fid in data.file_ids:
                file_row = get_file_identity(fid)
                conn.execute(
                    f"""DELETE FROM collection_items
                        WHERE collection_id=? AND {user_file_lookup_sql()}""",
                    [collection_id, *user_file_lookup_params(file_row)],
                )
                added_at_by_file[str(fid)] = None
        conn.commit()
    single_added_at = next(iter(added_at_by_file.values()), None) if len(added_at_by_file) == 1 else None
    return {
        "status": "updated",
        "added_at": single_added_at,
        "added_at_by_file": added_at_by_file,
    }
