"""User-tag listing for the Danbooru module's tags browser.

Moved verbatim from ``core.py``. Queries the user database's ``user_image_tags``
joined against the indexed library. No ``core`` import.
"""
from __future__ import annotations

import re
from typing import Any

from config import USER_DB_PATH
from database import get_data_db
from models import PaginatedTags, TagInfo
from services.query_helpers import user_file_match
from services.tag_names import normalize_user_tag_category


def list_user_tags(
    category: str | None,
    q: str,
    letter: str | None,
    sort: str,
    order: str,
    offset: int,
    limit: int,
    min_count: int,
) -> PaginatedTags:
    where_parts: list[str] = []
    where_params: list[Any] = []
    if category:
        where_parts.append("uit.tag_category = ?")
        where_params.append(normalize_user_tag_category(category))
    if q:
        where_parts.append("uit.tag_name LIKE ?")
        where_params.append(f"%{q}%")
    if letter:
        letter = letter.strip().upper()
        if letter == "#":
            where_parts.append("LOWER(SUBSTR(uit.tag_name, 1, 1)) NOT BETWEEN 'a' AND 'z'")
        elif re.fullmatch(r"[A-Z]", letter):
            where_parts.append("LOWER(uit.tag_name) LIKE ?")
            where_params.append(f"{letter.lower()}%")
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    having_sql = "HAVING COUNT(DISTINCT f.id) >= ?"
    params = [*where_params, min_count]

    sort_col = {
        "count": "cnt",
        "alpha": "uit.tag_name",
        "length": "LENGTH(uit.tag_name)",
        "category": "uit.tag_category",
    }.get(sort, "cnt")
    order_dir = "ASC" if order.lower() == "asc" else "DESC"

    with get_data_db() as conn:
        conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))
        count_row = conn.execute(
            f"""SELECT COUNT(*) as total FROM (
                    SELECT uit.tag_category, uit.tag_name, COUNT(DISTINCT f.id) as cnt
                    FROM userdb.user_image_tags uit
                    JOIN files f ON {user_file_match("uit")}
                    {where_sql}
                    GROUP BY uit.tag_category, uit.tag_name
                    {having_sql}
                )""",
            params,
        ).fetchone()
        total = count_row["total"]

        rows = conn.execute(
            f"""SELECT uit.tag_name as name, uit.tag_category as category, COUNT(DISTINCT f.id) as cnt
                FROM userdb.user_image_tags uit
                JOIN files f ON {user_file_match("uit")}
                {where_sql}
                GROUP BY uit.tag_category, uit.tag_name
                {having_sql}
                ORDER BY {sort_col} {order_dir}, uit.tag_name ASC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()

    tags = [TagInfo(name=r["name"], category=r["category"], count=r["cnt"]) for r in rows]
    return PaginatedTags(tags=tags, total=total, offset=offset, limit=limit)
