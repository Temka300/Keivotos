from __future__ import annotations

from fastapi import APIRouter
from core import *  # shared query, database, and media helpers

router = APIRouter()


@router.put("/api/favorites/batch")
def update_favorites_batch(data: FavoriteBatchUpdate):
    file_ids = list(dict.fromkeys(data.file_ids))
    if not file_ids:
        return {"status": "updated", "updated_file_ids": [], "added_at_by_file": {}}
    placeholders = ",".join("?" for _ in file_ids)
    with get_data_db() as conn:
        file_rows = conn.execute(
            f"SELECT id as file_id, path, local_md5 FROM files WHERE id IN ({placeholders})",
            file_ids,
        ).fetchall()
    rows_by_id = {row["file_id"]: row for row in file_rows}
    missing = [file_id for file_id in file_ids if file_id not in rows_by_id]
    if missing:
        raise HTTPException(404, f"Files not found: {', '.join(str(file_id) for file_id in missing[:10])}")

    added_at_by_file: dict[str, str | None] = {}
    with get_user_db() as conn:
        for file_id in file_ids:
            file_row = rows_by_id[file_id]
            if data.action == "add":
                conn.execute(
                    "INSERT OR IGNORE INTO favorites (file_id, file_path, local_md5) VALUES (?, ?, ?)",
                    (file_id, file_row["path"], file_row["local_md5"]),
                )
                favorite = conn.execute(
                    f"SELECT added_at FROM favorites WHERE {user_file_lookup_sql()}",
                    user_file_lookup_params(file_row),
                ).fetchone()
                added_at_by_file[str(file_id)] = favorite["added_at"] if favorite else None
            else:
                conn.execute(
                    f"DELETE FROM favorites WHERE {user_file_lookup_sql()}",
                    user_file_lookup_params(file_row),
                )
                added_at_by_file[str(file_id)] = None
        conn.commit()
    clear_home_caches()
    return {
        "status": "updated",
        "updated_file_ids": file_ids,
        "added_at_by_file": added_at_by_file,
    }


@router.post("/api/favorites/{file_id}")
def toggle_favorite(file_id: int):
    file_row = get_file_identity(file_id)
    with get_user_db() as conn:
        existing = conn.execute(
            f"SELECT 1 FROM favorites WHERE {user_file_lookup_sql()}",
            user_file_lookup_params(file_row),
        ).fetchone()
        if existing:
            conn.execute(
                f"DELETE FROM favorites WHERE {user_file_lookup_sql()}",
                user_file_lookup_params(file_row),
            )
            conn.commit()
            clear_home_caches()
            return {"status": "removed", "added_at": None}
        conn.execute(
            "INSERT INTO favorites (file_id, file_path, local_md5) VALUES (?, ?, ?)",
            (file_id, file_row["path"], file_row["local_md5"]),
        )
        conn.commit()
        row = conn.execute("SELECT added_at FROM favorites WHERE file_id=?", (file_id,)).fetchone()
        clear_home_caches()
        return {"status": "added", "added_at": row["added_at"] if row else None}


@router.get("/api/favorites/ids")
def favorite_ids():
    with get_data_db() as conn:
        conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))
        rows = conn.execute(
            f"""SELECT f.id as file_id, MAX(fav.added_at) as added_at
                FROM files f
                JOIN userdb.favorites fav ON {user_file_match("fav")}
                GROUP BY f.id
                ORDER BY added_at DESC"""
        ).fetchall()
    return [r["file_id"] for r in rows]


@router.post("/api/favorites/{file_id}/pin")
def toggle_favorite_pin(file_id: int):
    file_row = get_file_identity(file_id)
    with get_user_db() as conn:
        existing = conn.execute(
            f"SELECT pinned_at FROM favorites WHERE {user_file_lookup_sql()}",
            user_file_lookup_params(file_row),
        ).fetchone()
        if not existing:
            raise HTTPException(400, "Only favorited images can be pinned")
        if existing["pinned_at"]:
            conn.execute(
                f"UPDATE favorites SET pinned_at=NULL WHERE {user_file_lookup_sql()}",
                user_file_lookup_params(file_row),
            )
            conn.commit()
            return {"status": "unpinned", "pinned_at": None}
        conn.execute(
            f"UPDATE favorites SET pinned_at=datetime('now') WHERE {user_file_lookup_sql()}",
            user_file_lookup_params(file_row),
        )
        conn.commit()
        row = conn.execute(
            f"SELECT pinned_at FROM favorites WHERE {user_file_lookup_sql()}",
            user_file_lookup_params(file_row),
        ).fetchone()
        return {"status": "pinned", "pinned_at": row["pinned_at"] if row else None}


@router.post("/api/favorite-tags/{tag_name}")
def toggle_favorite_tag(tag_name: str, category: str = Query(...)):
    with get_user_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM favorite_tags WHERE tag_name=? AND tag_category=?",
            (tag_name, category),
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM favorite_tags WHERE tag_name=? AND tag_category=?",
                (tag_name, category),
            )
            conn.commit()
            clear_home_caches()
            return {"status": "removed"}
        conn.execute(
            "INSERT INTO favorite_tags (tag_name, tag_category) VALUES (?, ?)",
            (tag_name, category),
        )
        conn.commit()
        clear_home_caches()
        return {"status": "added"}


@router.post("/api/favorite-tags/{tag_name}/pin")
def toggle_favorite_tag_pin(tag_name: str, category: str = Query(...)):
    with get_user_db() as conn:
        existing = conn.execute(
            "SELECT pinned_at FROM favorite_tags WHERE tag_name=? AND tag_category=?",
            (tag_name, category),
        ).fetchone()
        if not existing:
            raise HTTPException(400, "Only favorited tags can be pinned")
        if existing["pinned_at"]:
            conn.execute(
                "UPDATE favorite_tags SET pinned_at=NULL WHERE tag_name=? AND tag_category=?",
                (tag_name, category),
            )
            conn.commit()
            return {"status": "unpinned", "pinned_at": None}
        conn.execute(
            "UPDATE favorite_tags SET pinned_at=datetime('now') WHERE tag_name=? AND tag_category=?",
            (tag_name, category),
        )
        conn.commit()
        row = conn.execute(
            "SELECT pinned_at FROM favorite_tags WHERE tag_name=? AND tag_category=?",
            (tag_name, category),
        ).fetchone()
        return {"status": "pinned", "pinned_at": row["pinned_at"] if row else None}


@router.get("/api/favorite-tags")
def list_favorite_tags():
    with get_user_db() as conn:
        rows = conn.execute(
            """SELECT tag_name, tag_category, added_at, pinned_at
               FROM favorite_tags
               ORDER BY CASE WHEN pinned_at IS NULL THEN 1 ELSE 0 END,
                        pinned_at DESC,
                        added_at DESC"""
        ).fetchall()

    fav_names = [(r["tag_name"], r["tag_category"]) for r in rows]
    if not fav_names:
        return {}
    fav_meta = {(r["tag_name"], r["tag_category"]): r for r in rows}

    with get_data_db() as conn:
        placeholders = ",".join("?" * len(fav_names))
        tag_names = [n for n, _ in fav_names]
        count_rows = conn.execute(
            f"""SELECT t.name, t.category, COUNT(pt.post_id) as cnt
                FROM tags t
                JOIN post_tags pt ON pt.tag_id = t.id
                WHERE t.name IN ({placeholders})
                GROUP BY t.id""",
            tag_names,
        ).fetchall()

    counts = {(r["name"], r["category"]): r["cnt"] for r in count_rows}

    result: dict[str, list[dict]] = {}
    for name, cat in fav_names:
        meta = fav_meta[(name, cat)]
        result.setdefault(cat, []).append({
            "name": name,
            "category": cat,
            "count": counts.get((name, cat), 0),
            "favorite_added_at": meta["added_at"],
            "pinned_at": meta["pinned_at"],
        })
    return result


@router.get("/api/favorite-tags/names")
def favorite_tag_names():
    with get_user_db() as conn:
        rows = conn.execute(
            """SELECT tag_name, tag_category, pinned_at
               FROM favorite_tags
               ORDER BY CASE WHEN pinned_at IS NULL THEN 1 ELSE 0 END,
                        pinned_at DESC,
                        added_at DESC"""
        ).fetchall()
    return [
        {"name": r["tag_name"], "category": r["tag_category"], "pinned_at": r["pinned_at"]}
        for r in rows
    ]


@router.get("/api/favorite-tag-combos", response_model=list[FavoriteTagComboInfo])
def list_favorite_tag_combos():
    with get_user_db() as conn:
        rows = conn.execute(
            "SELECT id, name, tags_json, added_at FROM favorite_tag_combos ORDER BY added_at DESC"
        ).fetchall()
    return [_combo_from_row(row) for row in rows]


@router.post("/api/favorite-tag-combos", response_model=FavoriteTagComboInfo)
def create_favorite_tag_combo(data: FavoriteTagComboCreate):
    tags = _normalize_combo_tags(data.tags)
    if len(tags) < 2:
        raise HTTPException(400, "A tag combo needs at least two tags")

    tag_key = _combo_key(tags)
    name = _combo_name(data.name, tags)
    tags_json = json.dumps(tags, ensure_ascii=False)
    with get_user_db() as conn:
        row = conn.execute(
            """
            INSERT INTO favorite_tag_combos (name, tag_key, tags_json)
            VALUES (?, ?, ?)
            ON CONFLICT(tag_key) DO UPDATE SET
                name = excluded.name,
                tags_json = excluded.tags_json
            RETURNING id, name, tags_json, added_at
            """,
            (name, tag_key, tags_json),
        ).fetchone()
        conn.commit()
    return _combo_from_row(row)


@router.delete("/api/favorite-tag-combos/{combo_id}")
def delete_favorite_tag_combo(combo_id: int):
    with get_user_db() as conn:
        conn.execute("DELETE FROM favorite_tag_combos WHERE id=?", (combo_id,))
        conn.commit()
    return {"status": "deleted", "id": combo_id}


@router.post("/api/blacklist-tags/{tag_name}")
def add_blacklist_tag(tag_name: str):
    name = _normalize_tag_name(tag_name)
    if not name:
        raise HTTPException(400, "Tag name is required")
    with get_user_db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO blacklist_tags (tag_name) VALUES (?)",
            (name,),
        )
        conn.commit()
    return {"status": "added" if cur.rowcount else "exists", "name": name}


@router.delete("/api/blacklist-tags/{tag_name}")
def remove_blacklist_tag(tag_name: str):
    name = _normalize_tag_name(tag_name)
    with get_user_db() as conn:
        cur = conn.execute("DELETE FROM blacklist_tags WHERE tag_name=?", (name,))
        conn.commit()
    return {"status": "removed" if cur.rowcount else "missing", "name": name}


@router.get("/api/blacklist-tags", response_model=list[TagInfo])
def list_blacklist_tags():
    with get_user_db() as conn:
        rows = conn.execute(
            "SELECT tag_name FROM blacklist_tags ORDER BY added_at DESC"
        ).fetchall()

    names = [r["tag_name"] for r in rows]
    if not names:
        return []

    with get_data_db() as conn:
        placeholders = ",".join("?" * len(names))
        tag_rows = conn.execute(
            f"""SELECT t.name, t.category, COUNT(pt.post_id) as cnt
                FROM tags t
                LEFT JOIN post_tags pt ON pt.tag_id = t.id
                WHERE t.name IN ({placeholders})
                GROUP BY t.id""",
            names,
        ).fetchall()

    indexed = {
        r["name"]: TagInfo(name=r["name"], category=r["category"], count=r["cnt"])
        for r in tag_rows
    }
    return [
        indexed.get(name, TagInfo(name=name, category="unknown", count=0))
        for name in names
    ]


@router.get("/api/blacklist-tags/names")
def blacklist_tag_names():
    with get_user_db() as conn:
        rows = conn.execute("SELECT tag_name FROM blacklist_tags ORDER BY added_at DESC").fetchall()
    return [r["tag_name"] for r in rows]
