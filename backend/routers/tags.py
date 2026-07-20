from __future__ import annotations

from fastapi import APIRouter
from core import *  # shared query, database, and media helpers

router = APIRouter()


@router.get("/api/tags", response_model=PaginatedTags)
def list_tags(
    category: str | None = None,
    q: str = "",
    letter: str | None = None,
    sort: str = "count",
    order: str = "desc",
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    min_count: int = Query(1, ge=1),
    source: str = "danbooru",
):
    tag_source = source.strip().lower()
    if tag_source in {"user", "user-added", "user_added"}:
        return list_user_tags(category, q, letter, sort, order, offset, limit, min_count)

    where_parts: list[str] = []
    where_params: list[Any] = []
    if category:
        where_parts.append("t.category = ?")
        where_params.append(category)
    if q:
        where_parts.append("t.name LIKE ?")
        where_params.append(f"%{q}%")
    if letter:
        letter = letter.strip().upper()
        if letter == "#":
            where_parts.append("LOWER(SUBSTR(t.name, 1, 1)) NOT BETWEEN 'a' AND 'z'")
        elif re.fullmatch(r"[A-Z]", letter):
            where_parts.append("LOWER(t.name) LIKE ?")
            where_params.append(f"{letter.lower()}%")
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    having_sql = "HAVING COUNT(pt.post_id) >= ?"
    params = [*where_params, min_count]

    sort_col = {
        "count": "cnt",
        "alpha": "name",
        "length": "LENGTH(name)",
        "category": "category",
    }.get(sort, "cnt")
    order_dir = "ASC" if order.lower() == "asc" else "DESC"

    with get_data_db() as conn:
        rows = conn.execute(
            f"""WITH counted_tags AS (
                    SELECT t.name as name, t.category as category, COUNT(pt.post_id) as cnt
                    FROM tags t
                    JOIN post_tags pt ON pt.tag_id = t.id
                    {where_sql}
                    GROUP BY t.id
                    {having_sql}
                )
                SELECT name, category, cnt, COUNT(*) OVER() as total
                FROM counted_tags
                ORDER BY {sort_col} {order_dir}, name ASC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()
        total = rows[0]["total"] if rows else 0
        if not rows and offset:
            count_row = conn.execute(
                f"""SELECT COUNT(*) as total FROM (
                        SELECT t.id
                        FROM tags t
                        JOIN post_tags pt ON pt.tag_id = t.id
                        {where_sql}
                        GROUP BY t.id
                        {having_sql}
                    )""",
                params,
            ).fetchone()
            total = count_row["total"]
    tags = [TagInfo(name=r["name"], category=r["category"], count=r["cnt"]) for r in rows]
    return PaginatedTags(tags=tags, total=total, offset=offset, limit=limit)


@router.get("/api/tags/{tag_name}/wiki", response_model=TagWikiInfo)
def tag_wiki(tag_name: str, refresh: bool = False, category: str | None = None):
    name = normalize_search_tag(tag_name)
    normalized_category = category.strip().lower() if category else None
    if not name:
        raise HTTPException(400, "Tag name is required")

    with get_user_db() as conn:
        row = conn.execute(
            "SELECT * FROM tag_wiki_cache WHERE tag_name=?",
            (name,),
        ).fetchone()

        if (
            row
            and not refresh
            and tag_wiki_cache_fresh(row)
            and tag_wiki_cache_complete_for_category(row, normalized_category)
        ):
            return tag_wiki_info_from_cache_row(name, row)

        try:
            values = fetch_tag_wiki_values(name, normalized_category)
        except HTTPException as exc:
            if exc.status_code == 404:
                missing_row = save_tag_wiki_cache(
                    conn,
                    name,
                    {
                        "title": name,
                        "other_names": [],
                        "body": "",
                        "aliases": [],
                        "implications": [],
                        "artist_id": None,
                        "artist_name": None,
                        "artist_group_name": None,
                        "artist_urls": [],
                        "artist_urls_checked": normalized_category == "artist",
                        "status": "missing",
                        "error": None,
                    },
                )
                return tag_wiki_info_from_cache_row(name, missing_row)
            if row:
                return tag_wiki_info_from_cache_row(name, row, str(exc.detail))
            return TagWikiInfo(
                tag_name=name,
                title=name,
                available=False,
                error=str(exc.detail),
            )

        updated = save_tag_wiki_cache(conn, name, values)
        return tag_wiki_info_from_cache_row(name, updated)
