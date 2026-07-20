from __future__ import annotations

from fastapi import APIRouter
from core import *  # shared query, database, and media helpers

router = APIRouter()


@router.post("/api/artist-profile-assets/refresh-followed", response_model=ArtistProfileBulkArchiveResult)
def refresh_followed_artist_profile_assets():
    with get_user_db() as conn:
        rows = conn.execute("SELECT tag_name FROM artist_follows ORDER BY added_at DESC, tag_name").fetchall()
    saved_count = 0
    unchanged_count = 0
    errors: list[str] = []
    for row in rows:
        tag_name = row["tag_name"]
        result = archive_artist_profile_media(tag_name)
        saved_count += result.saved_count
        unchanged_count += result.unchanged_count
        errors.extend(f"{tag_name}: {error}" for error in result.errors)
    return ArtistProfileBulkArchiveResult(
        checked_artists=len(rows),
        saved_count=saved_count,
        unchanged_count=unchanged_count,
        errors=errors,
    )


@router.get("/api/artist-profile-assets/{tag_name}", response_model=list[ArtistProfileAsset])
def list_artist_profile_assets(tag_name: str):
    name = normalize_search_tag(tag_name)
    if not name:
        raise HTTPException(400, "Artist tag is required")
    with get_user_db() as conn:
        return list_artist_profile_assets_from_conn(conn, name)


@router.post("/api/artist-profile-assets/{tag_name}/refresh", response_model=ArtistProfileArchiveResult)
def refresh_artist_profile_assets(tag_name: str):
    name = normalize_search_tag(tag_name)
    if not name:
        raise HTTPException(400, "Artist tag is required")
    return archive_artist_profile_media(name)


@router.get("/api/artist-profile-asset-files/{asset_id}")
def artist_profile_asset_file(asset_id: int):
    with get_user_db() as conn:
        row = conn.execute("SELECT file_path FROM artist_profile_assets WHERE id=?", (asset_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Archived artist profile image not found")
    archive_root = ARTIST_PROFILE_ARCHIVE_DIR.resolve(strict=False)
    path = Path(row["file_path"]).resolve(strict=False)
    try:
        path.relative_to(archive_root)
    except ValueError as exc:
        raise HTTPException(403, "Archived profile image is outside the archive") from exc
    if not path.is_file():
        raise HTTPException(404, "Archived artist profile image file is missing")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/api/artist-follows", response_model=list[ArtistFollowInfo])
def list_artist_follows():
    with get_user_db() as conn:
        rows = conn.execute(
            """SELECT *
               FROM artist_follows
               ORDER BY added_at DESC, tag_name ASC"""
        ).fetchall()
        for row in rows:
            seed_artist_follow_posts_from_cache(conn, row["tag_name"])
        conn.commit()
        return [artist_follow_info_from_row(conn, row) for row in rows]


@router.get("/api/artist-follows/names")
def artist_follow_names():
    with get_user_db() as conn:
        rows = conn.execute(
            """SELECT tag_name, tag_category, added_at
               FROM artist_follows
               ORDER BY added_at DESC, tag_name ASC"""
        ).fetchall()
    return [
        {"name": row["tag_name"], "category": row["tag_category"], "added_at": row["added_at"]}
        for row in rows
    ]


@router.post("/api/artist-follows/{tag_name}", response_model=ArtistFollowInfo)
def follow_artist(tag_name: str, display_name: str | None = None):
    name = normalize_search_tag(tag_name)
    if not name:
        raise HTTPException(400, "Artist tag is required")

    cleaned_display_name = display_name.strip() if display_name else None
    with get_user_db() as conn:
        conn.execute(
            """INSERT INTO artist_follows (tag_name, tag_category, display_name)
               VALUES (?, 'artist', ?)
               ON CONFLICT(tag_name) DO UPDATE SET
                   tag_category='artist',
                   display_name=COALESCE(excluded.display_name, artist_follows.display_name)""",
            (name, cleaned_display_name),
        )
        seed_artist_follow_posts_from_cache(conn, name)
        conn.commit()
        return load_artist_follow(conn, name)


@router.delete("/api/artist-follows/{tag_name}")
def unfollow_artist(tag_name: str):
    name = normalize_search_tag(tag_name)
    if not name:
        raise HTTPException(400, "Artist tag is required")
    with get_user_db() as conn:
        conn.execute("DELETE FROM artist_follows WHERE tag_name=?", (name,))
        conn.commit()
    return {"status": "removed", "name": name}


@router.post("/api/artist-follows/{tag_name}/check", response_model=ArtistFollowCheckResult)
def check_artist_danbooru_posts(
    tag_name: str,
    limit: int = Query(12, ge=1, le=50),
    initialize_notifications: bool = Query(False),
):
    name = normalize_search_tag(tag_name)
    if not name:
        raise HTTPException(400, "Artist tag is required")
    post_ids = fetch_artist_danbooru_post_ids(name, limit)

    with get_user_db() as conn:
        row = conn.execute("SELECT * FROM artist_follows WHERE tag_name=?", (name,)).fetchone()
        if not row:
            raise HTTPException(404, "Artist follow not found")
        establishing_notification_baseline = initialize_notifications and not row.get("notification_initialized_at")

        discovered = 0
        for post_id in post_ids:
            conn.execute(
                """INSERT OR IGNORE INTO artist_follow_posts (tag_name, danbooru_post_id)
                   VALUES (?, ?)""",
                (name, post_id),
            )
            discovered += conn.execute("SELECT changes() as cnt").fetchone()["cnt"]
        if establishing_notification_baseline:
            conn.execute(
                "UPDATE artist_follow_posts SET seen_at=COALESCE(seen_at, datetime('now')) WHERE tag_name=?",
                (name,),
            )
            latest_row = conn.execute(
                "SELECT MAX(danbooru_post_id) as post_id FROM artist_follow_posts WHERE tag_name=?",
                (name,),
            ).fetchone()
            latest_post_id = int_or_none(latest_row["post_id"] if latest_row else None)
            conn.execute(
                """UPDATE artist_follows
                      SET notification_initialized_at=datetime('now'),
                          last_seen_danbooru_post_id=COALESCE(?, last_seen_danbooru_post_id)
                    WHERE tag_name=?""",
                (latest_post_id, name),
            )
            discovered = 0
        conn.execute(
            "UPDATE artist_follows SET last_checked_at=datetime('now') WHERE tag_name=?",
            (name,),
        )
        conn.commit()
        follow = load_artist_follow(conn, name)
    return ArtistFollowCheckResult(follow=follow, discovered_count=discovered)


@router.post("/api/artist-follows/{tag_name}/seen", response_model=ArtistFollowInfo)
def mark_artist_follow_seen(tag_name: str):
    name = normalize_search_tag(tag_name)
    if not name:
        raise HTTPException(400, "Artist tag is required")
    with get_user_db() as conn:
        row = conn.execute("SELECT * FROM artist_follows WHERE tag_name=?", (name,)).fetchone()
        if not row:
            raise HTTPException(404, "Artist follow not found")
        latest_row = conn.execute(
            "SELECT MAX(danbooru_post_id) as post_id FROM artist_follow_posts WHERE tag_name=?",
            (name,),
        ).fetchone()
        latest_post_id = int_or_none(latest_row["post_id"] if latest_row else None)
        conn.execute(
            "UPDATE artist_follow_posts SET seen_at=datetime('now') WHERE tag_name=? AND seen_at IS NULL",
            (name,),
        )
        conn.execute(
            "UPDATE artist_follows SET last_seen_danbooru_post_id=COALESCE(?, last_seen_danbooru_post_id) WHERE tag_name=?",
            (latest_post_id, name),
        )
        conn.commit()
        return load_artist_follow(conn, name)


@router.get("/api/tags/random", response_model=TagInfo)
def random_tag(
    category: str | None = None,
    min_count: int = Query(1, ge=0),
):
    where = []
    params: list[Any] = []
    if category:
        where.append("t.category=?")
        params.append(category)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with get_data_db() as conn:
        row = conn.execute(
            f"""SELECT t.name, t.category, COUNT(pt.post_id) as cnt
                FROM tags t
                JOIN post_tags pt ON pt.tag_id = t.id
                {where_sql}
                GROUP BY t.id
                HAVING cnt >= ?
                ORDER BY RANDOM()
                LIMIT 1""",
            [*params, min_count],
        ).fetchone()

    if not row:
        raise HTTPException(404, "No matching tag")
    return TagInfo(name=row["name"], category=row["category"], count=row["cnt"])


@router.get("/api/tags/suggest", response_model=list[TagInfo])
def suggest_tags(
    q: str = "",
    category: str | None = None,
    limit: int = Query(20, ge=1, le=100),
):
    q = normalize_search_tag(q)
    if not q:
        return []
    where = ["t.name LIKE ?"]
    params: list[Any] = [f"%{q}%"]
    if category:
        where.append("t.category=?")
        params.append(normalize_user_tag_category(category))
    with get_data_db() as conn:
        rows = conn.execute(
            """SELECT t.name, t.category, COUNT(pt.post_id) as cnt
               FROM tags t
               JOIN post_tags pt ON pt.tag_id = t.id
               WHERE {where_sql}
               GROUP BY t.id
               ORDER BY CASE
                            WHEN t.name = ? THEN 0
                            WHEN t.name LIKE ? THEN 1
                            ELSE 2
                        END,
                        cnt DESC,
                        t.name ASC
               LIMIT ?""".format(where_sql=" AND ".join(where)),
            [*params, q, f"{q}%", limit],
        ).fetchall()
    return [TagInfo(name=r["name"], category=r["category"], count=r["cnt"]) for r in rows]


@router.get("/api/tags/related", response_model=dict[str, list[TagInfo]])
def related_tags(
    tags: str = Query(..., description="Comma-separated tag names"),
    limit: int = Query(30, ge=1, le=200),
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    if not tag_list:
        return {}

    with get_data_db() as conn:
        tag_placeholders = ",".join("?" * len(tag_list))
        n = len(tag_list)

        searched_rows = conn.execute(
            f"""SELECT t.name, t.category, COUNT(pt.post_id) as cnt
                FROM tags t
                JOIN post_tags pt ON pt.tag_id = t.id
                WHERE t.name IN ({tag_placeholders})
                GROUP BY t.id""",
            tag_list,
        ).fetchall()

        rows = conn.execute(
            f"""SELECT t2.name, t2.category, COUNT(DISTINCT pt1.post_id) as cnt
                FROM post_tags pt1
                JOIN post_tags pt2 ON pt2.post_id = pt1.post_id
                JOIN tags t1 ON t1.id = pt1.tag_id
                JOIN tags t2 ON t2.id = pt2.tag_id
                WHERE t1.name IN ({tag_placeholders})
                  AND t2.name NOT IN ({tag_placeholders})
                  AND t2.category IN ('character','artist','copyright','general','meta')
                GROUP BY t2.id
                HAVING COUNT(DISTINCT t1.name) = ?
                ORDER BY cnt DESC""",
            [*tag_list, *tag_list, n],
        ).fetchall()

    result: dict[str, list[TagInfo]] = {"all": []}
    for r in searched_rows:
        cat = r["category"]
        if cat in ('character', 'artist', 'copyright', 'general', 'meta'):
            result.setdefault(cat, []).append(
                TagInfo(name=r["name"], category=r["category"], count=r["cnt"])
            )
    for r in rows:
        cat = r["category"]
        tag = TagInfo(name=r["name"], category=r["category"], count=r["cnt"])
        if len(result["all"]) < limit:
            result["all"].append(tag)
        if cat not in result:
            result[cat] = []
        if len(result[cat]) < limit:
            result[cat].append(tag)
    return result
