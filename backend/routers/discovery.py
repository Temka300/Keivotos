from __future__ import annotations

from fastapi import APIRouter
from core import *  # shared query, database, and media helpers

router = APIRouter()


@router.get("/api/popularity/periods", response_model=list[PopularityPeriod])
def popularity_periods(
    period: str = Query("day", pattern="^(day|month|year)$"),
    q: str = "",
    folder: str | None = None,
    rating: str | None = None,
    blacklist: str = "",
    limit: int = Query(100, ge=1, le=1000),
):
    search, exact_post_id, root_id = combined_image_search(q, folder, rating)

    inc, exc, filt = parse_search_terms(search.strip())
    if root_id:
        filt["root_id"] = root_id
    if blacklist and not exact_post_id:
        for tag in blacklist.split(","):
            tag = normalize_search_tag(tag)
            if tag:
                exc.append((None, tag))

    where_sql, params = build_where(inc, exc, filt)
    where_sql = add_where_clause(where_sql, "p.created_at IS NOT NULL AND p.created_at <> ''")
    attach_user_db = search_requires_user_db(inc, exc, filt)

    if period == "month":
        bucket_expr = "SUBSTR(p.created_at, 1, 7)"
        start_expr = "date(SUBSTR(p.created_at, 1, 7) || '-01')"
        end_expr = "date(SUBSTR(p.created_at, 1, 7) || '-01', '+1 month', '-1 day')"
    elif period == "year":
        bucket_expr = "SUBSTR(p.created_at, 1, 4)"
        start_expr = "date(SUBSTR(p.created_at, 1, 4) || '-01-01')"
        end_expr = "date(SUBSTR(p.created_at, 1, 4) || '-12-31')"
    else:
        bucket_expr = "date(p.created_at)"
        start_expr = "date(p.created_at)"
        end_expr = "date(p.created_at)"

    with get_data_db() as conn:
        if attach_user_db:
            conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))

        rows = conn.execute(
            f"""SELECT {bucket_expr} as period,
                      {bucket_expr} as label,
                      {start_expr} as start_date,
                      {end_expr} as end_date,
                      COUNT(*) as image_count,
                      CAST(SUM(COALESCE(p.score, 0)) AS INTEGER) as popularity,
                      AVG(COALESCE(p.score, 0)) as average_score,
                      CAST(MAX(COALESCE(p.score, 0)) AS INTEGER) as best_score
                FROM posts p
                JOIN files f ON f.id = p.file_id
                {where_sql}
                GROUP BY {bucket_expr}
                ORDER BY popularity DESC, image_count DESC, period DESC
                LIMIT ?""",
            [*params, limit],
        ).fetchall()

    return [PopularityPeriod(**row) for row in rows]


@router.get("/api/home/tags", response_model=HomeTags)
def home_tags(
    rating: str | None = Query(None, pattern=RATING_QUERY_PATTERN),
    featured_limit: int = Query(18, ge=1, le=40),
    group_limit: int = Query(24, ge=5, le=80),
):
    cache_key = ("home-tags", rating or "", featured_limit, group_limit)
    cached = home_cache_get(HOME_TAGS_CACHE, cache_key)
    if cached is not None:
        return cached

    rating_sql, rating_params = home_rating_clause(rating, "p")
    with get_data_db() as conn:
        conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))
        favorite_rows = conn.execute(
            f"""SELECT t.name, t.category, COUNT(pt.post_id) as cnt, MIN(ft.added_at) as added_at
               FROM userdb.favorite_tags ft
               JOIN tags t ON t.name = ft.tag_name AND t.category = ft.tag_category
               JOIN post_tags pt ON pt.tag_id = t.id
               JOIN posts p ON p.id = pt.post_id
               WHERE 1=1
                 {rating_sql}
               GROUP BY t.id
               HAVING cnt > 0
               ORDER BY added_at DESC, cnt DESC, t.name ASC
               LIMIT ?""",
            [*rating_params, featured_limit],
        ).fetchall()

        featured: list[HomeTagInfo] = []
        seen_featured: set[tuple[str, str]] = set()
        for tag in home_tag_infos_with_covers(conn, favorite_rows, rating):
            key = (tag.category, tag.name)
            seen_featured.add(key)
            featured.append(tag)

        if len(featured) < featured_limit:
            for category in ["character", "copyright", "artist", "general"]:
                rows = [
                    row
                    for row in top_tag_rows(conn, category, rating, featured_limit * 2)
                    if (row["category"], row["name"]) not in seen_featured
                ]
                for tag in home_tag_infos_with_covers(conn, rows, rating):
                    if len(featured) >= featured_limit:
                        break
                    key = (tag.category, tag.name)
                    if key in seen_featured:
                        continue
                    seen_featured.add(key)
                    featured.append(tag)
                if len(featured) >= featured_limit:
                    break

        groups = {
            category: home_tag_infos_with_covers(
                conn,
                top_tag_rows(conn, category, rating, group_limit),
                rating,
            )
            for category in HOME_TAG_CATEGORIES
        }

    return home_cache_set(HOME_TAGS_CACHE, cache_key, HomeTags(featured=featured, groups=groups))


@router.get("/api/home/image-rails", response_model=HomeImageRails)
def home_image_rails(
    rating: str | None = Query(None, pattern=RATING_QUERY_PATTERN),
    per_rail: int = Query(24, ge=8, le=60),
):
    cache_key = ("home-image-rails", rating or "", per_rail)
    cached = home_cache_get(HOME_IMAGE_RAILS_CACHE, cache_key)
    if cached is not None:
        return cached

    rating_sql, rating_params = home_rating_clause(rating, "p")
    with get_data_db() as conn:
        conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))

        rails: list[HomeImageRail] = []
        favorite_rows = conn.execute(
            f"""SELECT p.id,
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
                       1 as is_favorite
                FROM posts p
                JOIN files f ON f.id = p.file_id
                JOIN userdb.favorites fav ON {user_file_match("fav")}
                WHERE LOWER(COALESCE(f.ext, '')) NOT IN ('mp4', 'webm')
                  {rating_sql}
                GROUP BY p.id
                ORDER BY MAX(fav.added_at) DESC,
                         COALESCE(p.score, -999999) DESC,
                         COALESCE(p.created_at, '') DESC,
                         p.id DESC
                LIMIT ?""",
            [*rating_params, per_rail],
        ).fetchall()
        rails.append(
            HomeImageRail(
                key="favorites",
                label="Favorites",
                items=[home_image_rail_item(row, is_favorite=True) for row in favorite_rows],
            )
        )

        for category, label in HOME_IMAGE_RAIL_CATEGORIES[1:]:
            items: list[HomeImageRailItem] = []
            used_file_ids: set[int] = set()
            tag_rows = top_tag_rows(conn, category, rating, per_rail * 3)
            for cover in home_cover_rows_for_tags(conn, tag_rows, rating):
                if cover["file_id"] in used_file_ids:
                    continue
                used_file_ids.add(cover["file_id"])
                items.append(
                    home_image_rail_item(
                        cover,
                        tag_name=cover["tag_name"],
                        tag_category=cover["tag_category"],
                    )
                )
                if len(items) >= per_rail:
                    break
            rails.append(HomeImageRail(key=category, label=label, items=items))

    return home_cache_set(HOME_IMAGE_RAILS_CACHE, cache_key, HomeImageRails(rails=rails))


@router.get("/api/challenges/daily", response_model=DailyChallenge)
def daily_challenge(rating: str | None = Query(None, pattern=RATING_QUERY_PATTERN)):
    challenge_date = date.today().isoformat()
    seed = daily_challenge_seed(challenge_date, rating)
    with get_data_db() as conn:
        candidate = daily_challenge_candidate(conn, rating, seed, single_character_only=True)
        if candidate is None:
            candidate = daily_challenge_candidate(conn, rating, seed, single_character_only=False)
        if candidate is None:
            raise HTTPException(404, "No local character challenge candidates found")

        answer_tag = candidate["answer_tag"]
        answer_count = daily_challenge_tag_count(conn, answer_tag, rating)
        options = [
            DailyChallengeOption(name=answer_tag, count=answer_count),
            *daily_challenge_distractors(conn, answer_tag, rating, seed + candidate["id"], 5),
        ]
        random.Random(seed ^ candidate["id"]).shuffle(options)
        clues = daily_challenge_clues(conn, candidate)

    challenge_id = hashlib.sha1(
        f"{challenge_date}:{rating or 'all'}:{candidate['id']}:{answer_tag}".encode("utf-8")
    ).hexdigest()[:12]
    return DailyChallenge(
        date=challenge_date,
        challenge_id=challenge_id,
        image=daily_challenge_image_from_row(candidate),
        answer_tag=answer_tag,
        options=options,
        clues=clues,
        total_candidates=candidate["total_candidates"],
    )


@router.get("/api/challenges/characters/suggest", response_model=list[TagInfo])
def challenge_character_suggestions(
    q: str = "",
    rating: str | None = Query(None, pattern=RATING_QUERY_PATTERN),
    limit: int = Query(12, ge=1, le=30),
):
    raw = q.strip()
    if not raw:
        return []

    terms = re.findall(r"[a-z0-9]+", raw.lower())
    if not terms:
        normalized = normalize_search_tag(raw)
        terms = [normalized] if normalized else []
    if not terms:
        return []

    rating_sql, rating_params = home_rating_clause(rating, "p")
    where = ["t.category = 'character'"]
    params: list[Any] = []
    for term in terms:
        where.append("t.name LIKE ?")
        params.append(f"%{term}%")

    with get_data_db() as conn:
        rows = conn.execute(
            f"""SELECT t.name, t.category, COUNT(DISTINCT pt.post_id) as cnt
                FROM tags t
                JOIN post_tags pt ON pt.tag_id = t.id
                JOIN posts p ON p.id = pt.post_id
                WHERE {' AND '.join(where)}
                  {rating_sql}
                GROUP BY t.id
                HAVING cnt > 0
                ORDER BY cnt DESC, t.name ASC
                LIMIT 200""",
            [*params, *rating_params],
        ).fetchall()

    normalized = normalize_search_tag(raw)
    loose = challenge_loose_key(raw)

    def sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
        name = row["name"]
        name_loose = challenge_loose_key(name)
        if name == normalized or name_loose == loose:
            rank = 0
        elif name.startswith(normalized) or name_loose.startswith(loose):
            rank = 1
        else:
            rank = 2
        return (rank, -int(row["cnt"]), name)

    sorted_rows = sorted(rows, key=sort_key)[:limit]
    return [TagInfo(name=row["name"], category=row["category"], count=row["cnt"]) for row in sorted_rows]
