from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from models import HomeCoverCandidate, HomeImageRail, HomeImageRailItem, HomeImageRails, HomeTagInfo, HomeTags
from thumbnails import thumbnail_cache_token

from .query_helpers import normalize_rating_values, user_file_match

__all__ = [
    "HOME_TAG_CATEGORIES",
    "HOME_IMAGE_RAIL_CATEGORIES",
    "HOME_TAGS_CACHE",
    "HOME_IMAGE_RAILS_CACHE",
    "home_cache_get",
    "home_cache_set",
    "clear_home_caches",
    "home_rating_clause",
    "home_tag_infos_with_covers",
    "home_cover_rows_for_tags",
    "home_image_rail_item",
    "top_tag_rows",
]

HOME_CACHE_TTL_SECONDS = 300
HOME_TAG_CATEGORIES = ["character", "artist", "copyright", "general", "meta"]
HOME_IMAGE_RAIL_CATEGORIES = [
    ("favorites", "Favorites"),
    ("artist", "Artist"),
    ("general", "General"),
    ("character", "Character"),
    ("copyright", "Copyright"),
]
HOME_TAGS_CACHE: dict[tuple[Any, ...], tuple[float, HomeTags]] = {}
HOME_IMAGE_RAILS_CACHE: dict[tuple[Any, ...], tuple[float, HomeImageRails]] = {}
HOME_COVER_CANDIDATE_LIMIT = 6
HOME_COVER_ASPECT_ORDER_SQL = """
    CASE
        WHEN p.width IS NULL OR p.height IS NULL OR p.width <= 0 OR p.height <= 0 THEN 4
        WHEN (1.0 * p.width / p.height) BETWEEN 1.20 AND 2.40 THEN 0
        WHEN (1.0 * p.width / p.height) BETWEEN 0.90 AND 3.20 THEN 1
        WHEN (1.0 * p.width / p.height) BETWEEN 0.68 AND 0.90 THEN 2
        ELSE 3
    END ASC,
    CASE
        WHEN p.width IS NULL OR p.height IS NULL OR p.width <= 0 OR p.height <= 0 THEN 99.0
        ELSE ABS((1.0 * p.width / p.height) - 1.7777778)
    END ASC
"""


def home_cache_get(cache: dict[tuple[Any, ...], tuple[float, Any]], key: tuple[Any, ...]) -> Any | None:
    cached = cache.get(key)
    if cached is None:
        return None
    cached_at, value = cached
    if time.monotonic() - cached_at > HOME_CACHE_TTL_SECONDS:
        cache.pop(key, None)
        return None
    return value


def home_cache_set(cache: dict[tuple[Any, ...], tuple[float, Any]], key: tuple[Any, ...], value: Any) -> Any:
    cache[key] = (time.monotonic(), value)
    return value


def clear_home_caches() -> None:
    HOME_TAGS_CACHE.clear()
    HOME_IMAGE_RAILS_CACHE.clear()


def home_rating_clause(rating: str | None, alias: str = "p") -> tuple[str, list[Any]]:
    ratings = normalize_rating_values(rating)
    if ratings:
        placeholders = ",".join("?" for _ in ratings)
        return f"AND COALESCE(NULLIF({alias}.rating, ''), 'u') IN ({placeholders})", ratings
    return "", []


def home_tag_infos_with_covers(conn, rows: list[dict[str, Any]], rating: str | None) -> list[HomeTagInfo]:
    if not rows:
        return []

    rating_sql, rating_params = home_rating_clause(rating, "p")
    values_sql = ",".join("(?, ?, ?, ?)" for _ in rows)
    values_params: list[Any] = []
    for index, row in enumerate(rows):
        values_params.extend([row["name"], row["category"], index, row["cnt"]])

    cover_rows = conn.execute(
        f"""WITH selected_tags(name, category, ord, cnt) AS (
                VALUES {values_sql}
            ),
            ranked_covers AS (
                SELECT selected_tags.name,
                       selected_tags.category,
                       selected_tags.ord,
                       selected_tags.cnt,
                       p.id as cover_post_id,
                       f.id as cover_file_id,
                       f.path,
                       f.local_md5,
                       p.width,
                       p.height,
                       ROW_NUMBER() OVER (
                           PARTITION BY selected_tags.name, selected_tags.category
                           ORDER BY {HOME_COVER_ASPECT_ORDER_SQL},
                                    COALESCE(p.score, -999999) DESC,
                                    COALESCE(p.created_at, '') DESC,
                                    p.id DESC
                       ) as rn
                FROM selected_tags
                JOIN tags t ON t.name = selected_tags.name AND t.category = selected_tags.category
                JOIN post_tags pt ON pt.tag_id = t.id
                JOIN posts p ON p.id = pt.post_id
                JOIN files f ON f.id = p.file_id
                WHERE LOWER(COALESCE(f.ext, '')) NOT IN ('mp4', 'webm')
                  {rating_sql}
            )
            SELECT * FROM ranked_covers
            WHERE rn <= ?
            ORDER BY ord ASC, rn ASC""",
        [*values_params, *rating_params, HOME_COVER_CANDIDATE_LIMIT],
    ).fetchall()

    candidates_by_tag: dict[tuple[str, str], list[HomeCoverCandidate]] = {}
    for cover in cover_rows:
        key = (cover["category"], cover["name"])
        candidates_by_tag.setdefault(key, []).append(
            HomeCoverCandidate(
                post_id=cover["cover_post_id"],
                file_id=cover["cover_file_id"],
                thumbnail_token=cover["local_md5"] or thumbnail_cache_token(cover["path"]),
                width=cover["width"],
                height=cover["height"],
            )
        )

    result: list[HomeTagInfo] = []
    for row in rows:
        candidates = candidates_by_tag.get((row["category"], row["name"]), [])
        if not candidates:
            continue
        primary = candidates[0]
        result.append(
            HomeTagInfo(
                name=row["name"],
                category=row["category"],
                count=row["cnt"],
                cover_post_id=primary.post_id,
                cover_file_id=primary.file_id,
                thumbnail_token=primary.thumbnail_token,
                cover_candidates=candidates,
            )
        )
    return result


def home_cover_rows_for_tags(conn, rows: list[dict[str, Any]], rating: str | None) -> list[dict[str, Any]]:
    if not rows:
        return []
    rating_sql, rating_params = home_rating_clause(rating, "p")
    values_sql = ",".join("(?, ?, ?)" for _ in rows)
    values_params: list[Any] = []
    for index, row in enumerate(rows):
        values_params.extend([row["name"], row["category"], index])
    return conn.execute(
        f"""WITH selected_tags(name, category, ord) AS (
                VALUES {values_sql}
            ),
            ranked_covers AS (
                SELECT selected_tags.name as tag_name,
                       selected_tags.category as tag_category,
                       selected_tags.ord,
                       p.id,
                       f.id as file_id,
                       f.path,
                       f.local_md5,
                       f.name as filename,
                       f.folder,
                       f.ext,
                       p.width,
                       p.height,
                       p.score,
                       p.rating,
                       CASE WHEN EXISTS (
                           SELECT 1 FROM userdb.favorites fav WHERE {user_file_match("fav")}
                       ) THEN 1 ELSE 0 END as is_favorite,
                       ROW_NUMBER() OVER (
                           PARTITION BY selected_tags.name, selected_tags.category
                           ORDER BY {HOME_COVER_ASPECT_ORDER_SQL},
                                    COALESCE(p.score, -999999) DESC,
                                    COALESCE(p.created_at, '') DESC,
                                    p.id DESC
                        ) as rn,
                       COUNT(*) OVER (
                           PARTITION BY selected_tags.name, selected_tags.category
                       ) as candidate_count
                FROM selected_tags
                JOIN tags t ON t.name = selected_tags.name AND t.category = selected_tags.category
                JOIN post_tags pt ON pt.tag_id = t.id
                JOIN posts p ON p.id = pt.post_id
                JOIN files f ON f.id = p.file_id
                WHERE LOWER(COALESCE(f.ext, '')) NOT IN ('mp4', 'webm')
                  {rating_sql}
            )
            SELECT * FROM ranked_covers
            WHERE rn = 1 + ((ord + 2) % CASE WHEN candidate_count < 5 THEN candidate_count ELSE 5 END)
            ORDER BY ord ASC""",
        [*values_params, *rating_params],
    ).fetchall()


def home_image_rail_item(
    row: dict[str, Any],
    tag_name: str | None = None,
    tag_category: str | None = None,
    is_favorite: bool | None = None,
) -> HomeImageRailItem:
    post_id = row.get("id") or row.get("cover_post_id")
    file_id = row.get("file_id") or row.get("cover_file_id")
    return HomeImageRailItem(
        id=post_id,
        file_id=file_id,
        thumbnail_token=row["local_md5"] or thumbnail_cache_token(row["path"]),
        filename=row.get("filename") or Path(row["path"]).name,
        folder=row.get("folder"),
        ext=row.get("ext"),
        width=row.get("width"),
        height=row.get("height"),
        score=row.get("score"),
        rating=row.get("rating"),
        tag_name=tag_name,
        tag_category=tag_category,
        is_favorite=bool(row.get("is_favorite")) if is_favorite is None else is_favorite,
    )


def top_tag_rows(conn, category: str, rating: str | None, limit: int) -> list[dict[str, Any]]:
    rating_sql, rating_params = home_rating_clause(rating, "p")
    return conn.execute(
        f"""SELECT t.name, t.category, COUNT(pt.post_id) as cnt
            FROM tags t
            JOIN post_tags pt ON pt.tag_id = t.id
            JOIN posts p ON p.id = pt.post_id
            WHERE t.category=?
              {rating_sql}
            GROUP BY t.id
            HAVING cnt > 0
            ORDER BY cnt DESC, t.name ASC
            LIMIT ?""",
        [category, *rating_params, limit],
    ).fetchall()
