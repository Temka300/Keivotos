from __future__ import annotations

import hashlib
import re
from typing import Any

from models import DailyChallengeClues, DailyChallengeImage, DailyChallengeOption
from thumbnails import thumbnail_cache_token

from .home import home_rating_clause

__all__ = [
    "LOW_VALUE_CHALLENGE_GENERAL_TAGS",
    "daily_challenge_seed",
    "challenge_loose_key",
    "challenge_year",
    "daily_challenge_candidate",
    "daily_challenge_tag_count",
    "daily_challenge_distractors",
    "daily_challenge_image_from_row",
    "daily_challenge_clues",
]

LOW_VALUE_CHALLENGE_GENERAL_TAGS = {
    "1girl", "1boy", "2girls", "multiple_girls", "solo", "looking_at_viewer",
    "simple_background", "white_background", "transparent_background", "blush",
    "smile", "open_mouth", "closed_mouth", "standing", "sitting", "upper_body",
    "cowboy_shot", "full_body",
}


def daily_challenge_seed(challenge_date: str, rating: str | None) -> int:
    digest = hashlib.sha1(f"{challenge_date}:{rating or 'all'}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def challenge_loose_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def challenge_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"^(\d{4})", value)
    return int(match.group(1)) if match else None


def daily_challenge_candidate(conn, rating: str | None, seed: int, single_character_only: bool) -> dict[str, Any] | None:
    rating_sql, rating_params = home_rating_clause(rating, "p")
    character_having = "= 1" if single_character_only else ">= 1"
    rows = conn.execute(
        f"""WITH character_candidates AS (
                SELECT p.id, p.danbooru_post_id, p.created_at, p.width, p.height,
                       p.score, p.rating, f.id as file_id, f.path, f.local_md5,
                       f.name as filename, f.folder, f.ext, MIN(t.name) as answer_tag,
                       COUNT(DISTINCT t.id) as character_count
                FROM posts p
                JOIN files f ON f.id = p.file_id
                JOIN post_tags pt ON pt.post_id = p.id
                JOIN tags t ON t.id = pt.tag_id AND t.category = 'character'
                WHERE LOWER(COALESCE(f.ext, '')) NOT IN ('mp4', 'webm') {rating_sql}
                GROUP BY p.id
                HAVING COUNT(DISTINCT t.id) {character_having}
            )
            SELECT character_candidates.*, totals.total_candidates
            FROM character_candidates
            CROSS JOIN (SELECT COUNT(*) as total_candidates FROM character_candidates) totals
            ORDER BY ABS(((character_candidates.id * 1103515245) + ?) % 2147483647),
                     character_candidates.id ASC
            LIMIT 1""",
        [*rating_params, seed],
    ).fetchall()
    return rows[0] if rows else None


def daily_challenge_tag_count(conn, tag_name: str, rating: str | None) -> int:
    rating_sql, rating_params = home_rating_clause(rating, "p")
    row = conn.execute(
        f"""SELECT COUNT(DISTINCT pt.post_id) as cnt
            FROM tags t
            JOIN post_tags pt ON pt.tag_id = t.id
            JOIN posts p ON p.id = pt.post_id
            WHERE t.category = 'character' AND t.name = ? {rating_sql}""",
        [tag_name, *rating_params],
    ).fetchone()
    return int(row["cnt"] if row else 0)


def daily_challenge_distractors(
    conn, answer_tag: str, rating: str | None, seed: int, limit: int,
) -> list[DailyChallengeOption]:
    rating_sql, rating_params = home_rating_clause(rating, "p")
    rows = conn.execute(
        f"""SELECT t.name, COUNT(DISTINCT pt.post_id) as cnt
            FROM tags t
            JOIN post_tags pt ON pt.tag_id = t.id
            JOIN posts p ON p.id = pt.post_id
            WHERE t.category = 'character' AND t.name <> ? {rating_sql}
            GROUP BY t.id
            HAVING cnt > 0
            ORDER BY ABS(((t.id * 1103515245) + ?) % 2147483647), cnt DESC, t.name ASC
            LIMIT ?""",
        [answer_tag, *rating_params, seed, limit],
    ).fetchall()
    return [DailyChallengeOption(name=row["name"], count=row["cnt"]) for row in rows]


def daily_challenge_image_from_row(row: dict[str, Any]) -> DailyChallengeImage:
    return DailyChallengeImage(
        id=row["id"], file_id=row["file_id"],
        thumbnail_token=row["local_md5"] or thumbnail_cache_token(row["path"]),
        filename=row["filename"], folder=row["folder"], ext=row["ext"],
        width=row["width"], height=row["height"], score=row["score"], rating=row["rating"],
        created_at=row["created_at"], danbooru_post_id=row["danbooru_post_id"],
    )


def daily_challenge_clues(conn, row: dict[str, Any]) -> DailyChallengeClues:
    tag_rows = conn.execute(
        """SELECT t.name, t.category, COUNT(pt_all.post_id) as cnt
           FROM post_tags pt
           JOIN tags t ON t.id = pt.tag_id
           LEFT JOIN post_tags pt_all ON pt_all.tag_id = t.id
           WHERE pt.post_id=? AND t.category IN ('copyright', 'artist', 'general', 'meta')
           GROUP BY t.id
           ORDER BY cnt DESC, t.name ASC""",
        (row["id"],),
    ).fetchall()
    grouped: dict[str, list[str]] = {"copyright": [], "artist": [], "general": [], "meta": []}
    for tag_row in tag_rows:
        category, name = tag_row["category"], tag_row["name"]
        if category == "general" and name in LOW_VALUE_CHALLENGE_GENERAL_TAGS:
            continue
        if category in grouped:
            grouped[category].append(name)
    return DailyChallengeClues(
        copyrights=grouped["copyright"][:4], artists=grouped["artist"][:3],
        general=grouped["general"][:8], meta=grouped["meta"][:4], folder=row["folder"],
        rating=row["rating"], score=row["score"], year=challenge_year(row["created_at"]),
    )
