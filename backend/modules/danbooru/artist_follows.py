"""Followed-artist watchlist state and Danbooru post-ID tracking.

Moved verbatim from ``core.py``. Checking an artist records post IDs only — no
file is downloaded and no remote image is hotlinked; posts missing locally are
rendered as placeholders by the UI.

No ``core`` import.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from database import get_data_db
from models import ArtistFollowInfo, TagWikiExample
from modules.danbooru.client import danbooru_json
from modules.danbooru.relations import (
    related_info_from_row,
    related_infos_for_danbooru_ids,
)
from modules.danbooru.tag_wiki import parse_tag_wiki_body, tag_wiki_example
from services.value_helpers import int_or_none, unique_ints


ARTIST_FOLLOW_POST_LIMIT = 24


def seed_artist_follow_posts_from_cache(conn, tag_name: str) -> int:
    row = conn.execute(
        "SELECT body FROM tag_wiki_cache WHERE tag_name=?",
        (tag_name,),
    ).fetchone()
    if not row:
        return 0
    _description, example_ids, _sections = parse_tag_wiki_body(row.get("body") or "")
    if not example_ids:
        return 0

    inserted = 0
    for post_id in example_ids:
        conn.execute(
            """INSERT OR IGNORE INTO artist_follow_posts (tag_name, danbooru_post_id)
               VALUES (?, ?)""",
            (tag_name, post_id),
        )
        inserted += conn.execute("SELECT changes() as cnt").fetchone()["cnt"]
    return inserted


def artist_follow_local_count(tag_name: str) -> int:
    with get_data_db() as conn:
        row = conn.execute(
            """SELECT COUNT(DISTINCT p.id) as cnt
               FROM tags t
               JOIN post_tags pt ON pt.tag_id = t.id
               JOIN posts p ON p.id = pt.post_id
               WHERE t.name=? AND t.category='artist'""",
            (tag_name,),
        ).fetchone()
    return int(row["cnt"] if row else 0)


def artist_follow_posts(conn, tag_name: str, limit: int = ARTIST_FOLLOW_POST_LIMIT) -> list[TagWikiExample]:
    rows = conn.execute(
        """SELECT danbooru_post_id
           FROM artist_follow_posts
           WHERE tag_name=?
           ORDER BY CASE WHEN seen_at IS NULL THEN 0 ELSE 1 END,
                    discovered_at DESC,
                    danbooru_post_id DESC
           LIMIT ?""",
        (tag_name, limit),
    ).fetchall()
    post_ids = [int(row["danbooru_post_id"]) for row in rows]
    if not post_ids:
        return []
    with get_data_db() as data_conn:
        local_infos = related_infos_for_danbooru_ids(data_conn, post_ids)
    return [tag_wiki_example(post_id, local_infos) for post_id in post_ids]


def artist_follow_profile_post(tag_name: str) -> TagWikiExample | None:
    with get_data_db() as conn:
        row = conn.execute(
            """SELECT p.danbooru_post_id,
                      p.id as local_post_id,
                      f.id as file_id,
                      f.path,
                      f.name as filename,
                      f.folder,
                      f.ext,
                      f.local_md5,
                      p.width,
                      p.height,
                      p.score,
                      p.rating,
                      p.post_url,
                      p.created_at
               FROM tags t
               JOIN post_tags pt ON pt.tag_id = t.id
               JOIN posts p ON p.id = pt.post_id
               JOIN files f ON f.id = p.file_id
               WHERE t.name=? AND t.category='artist' AND p.danbooru_post_id IS NOT NULL
               ORDER BY COALESCE(p.score, -999999) DESC,
                        COALESCE(p.created_at, '') DESC,
                        p.id DESC
               LIMIT 1""",
            (tag_name,),
        ).fetchone()
    if not row:
        return None
    info = related_info_from_row(row)
    data = info.model_dump() if hasattr(info, "model_dump") else info.dict()
    return TagWikiExample(**data)


def artist_follow_info_from_row(conn, row: dict[str, Any]) -> ArtistFollowInfo:
    tag_name = row["tag_name"]
    unseen_row = conn.execute(
        """SELECT COUNT(*) as cnt
           FROM artist_follow_posts
           WHERE tag_name=? AND seen_at IS NULL""",
        (tag_name,),
    ).fetchone()
    return ArtistFollowInfo(
        tag_name=tag_name,
        tag_category=row.get("tag_category") or "artist",
        display_name=row.get("display_name") or None,
        local_count=artist_follow_local_count(tag_name),
        added_at=row["added_at"],
        last_checked_at=row.get("last_checked_at"),
        notification_initialized_at=row.get("notification_initialized_at"),
        last_seen_danbooru_post_id=int_or_none(row.get("last_seen_danbooru_post_id")),
        unseen_count=int(unseen_row["cnt"] if unseen_row else 0),
        profile_post=artist_follow_profile_post(tag_name),
        posts=artist_follow_posts(conn, tag_name),
    )


def load_artist_follow(conn, tag_name: str) -> ArtistFollowInfo:
    row = conn.execute(
        "SELECT * FROM artist_follows WHERE tag_name=?",
        (tag_name,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Artist follow not found")
    return artist_follow_info_from_row(conn, row)


def fetch_artist_danbooru_post_ids(tag_name: str, limit: int) -> list[int]:
    data = danbooru_json(
        "/posts.json",
        {
            "tags": f"{tag_name} order:id_desc",
            "limit": limit,
        },
        timeout=20.0,
    )
    if not isinstance(data, list):
        raise HTTPException(502, "Unexpected Danbooru posts payload")
    ids: list[int] = []
    for item in data:
        if isinstance(item, dict):
            post_id = int_or_none(item.get("id"))
            if post_id is not None:
                ids.append(post_id)
    return unique_ints(ids)
