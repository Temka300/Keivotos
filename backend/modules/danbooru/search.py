"""The Danbooru search grammar: parse a query, build the SQL predicate.

Moved verbatim from ``core.py``. This is the user-facing search syntax — plain
and negated tags, category prefixes, post IDs, filenames, dates, numeric and
dimension comparisons, shape presets, ratings, extension and folder filters —
translated into a WHERE clause over the Danbooru index.

Two rules this module keeps:

- The blacklist applies to every search *except* an exact post-ID lookup.
- This is the application's grammar. The standalone CLI search in
  ``scripts/danbooru_gallery_dl.py`` is deliberately separate; the two are not
  merged just because their names and shapes are similar
  (MODULAR_ARCHITECTURE_PLAN.md section 6).

No ``core`` import.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from services.query_helpers import normalize_rating_values, user_file_match
from services.tag_names import TAG_CATEGORIES, normalize_search_tag, normalize_user_tag


# TAG_CATEGORIES moved to services/tag_names.py; imported at the top.
USER_TAG_CATEGORY = "user"
NUMERIC_FILTERS = {"width", "w", "height", "h", "pixels", "mp", "ratio", "score"}
HEART_SPAM_FILTER_PREFIXES = {"heart", "hearts", "heart_spam", "heartspam"}
DIMENSION_FILTER_PREFIXES = {"res", "resolution", "dim", "dims", "dimension", "dimensions", "size"}
POST_ID_FILTER_PREFIXES = {"id", "post", "post_id", "danbooru", "danbooru_id", "danbooru_post_id"}
FILENAME_FILTER_PREFIXES = {"filename", "file", "name"}
SHAPE_FILTER_PREFIXES = {"shape", "aspect", "aspect_ratio", "preset"}
SHAPE_PRESET_ALIASES = {
    "vertical": "vertical",
    "portrait": "vertical",
    "horizontal": "horizontal",
    "landscape": "horizontal",
    "wide": "horizontal",
    "phone": "phone",
    "phones": "phone",
    "phone_sized": "phone",
    "phone_size": "phone",
    "phone_wallpaper": "phone",
    "phone_wallpapers": "phone",
    "mobile": "phone",
    "mobile_sized": "phone",
    "mobile_wallpaper": "phone",
    "banner": "banner",
    "banners": "banner",
    "banner_sized": "banner",
    "banner_size": "banner",
    "wide_banner": "banner",
    "header": "banner",
    "headers": "banner",
    "logo": "logo",
    "logos": "logo",
    "logo_sized": "logo",
    "logo_size": "logo",
    "icon": "logo",
    "icons": "logo",
    "avatar": "logo",
    "avatars": "logo",
    "square": "logo",
}
DIMENSION_TOKEN_RE = re.compile(r"(\d+)\s*[xX\u00d7]\s*(\d+)")
BARE_FILENAME_RE = re.compile(r".+\.(?:jpe?g|png|webp|gif|jfif|mp4|webm)$", re.IGNORECASE)
DATE_FILTER_PREFIXES = {
    "created": "uploaded",
    "created_at": "uploaded",
    "created_date": "uploaded",
    "uploaded": "uploaded",
    "uploaded_at": "uploaded",
    "upload_date": "uploaded",
    "downloaded": "downloaded",
    "downloaded_at": "downloaded",
    "downloaded_date": "downloaded",
}


def normalize_dimension_tokens(raw: str) -> str:
    return DIMENSION_TOKEN_RE.sub(r"\1x\2", raw)


def normalize_shape_term(value: str) -> str:
    return re.sub(r"[\s-]+", "_", value.strip().strip("\"'").lower())


def normalize_search_phrases(raw: str) -> str:
    value = normalize_dimension_tokens(raw)
    value = re.sub(r"\b(phone|mobile|banner|logo)\s+(sized?|wallpapers?)\b", r"\1_\2", value, flags=re.IGNORECASE)
    value = re.sub(r"\bwide\s+banner\b", "wide_banner", value, flags=re.IGNORECASE)
    return value


def add_dimension_filter(filters: dict[str, Any], value: str) -> bool:
    match = re.fullmatch(r"(>=|<=|>|<|=)?(\d+)x(\d+)", normalize_dimension_tokens(value).strip())
    if not match:
        return False

    op = match.group(1) or "="
    filters.setdefault("width", [])
    filters["width"].append(f"{op}{match.group(2)}")
    filters.setdefault("height", [])
    filters["height"].append(f"{op}{match.group(3)}")
    return True


def add_shape_filter(filters: dict[str, Any], value: str, negate: bool = False) -> bool:
    preset = SHAPE_PRESET_ALIASES.get(normalize_shape_term(value))
    if not preset:
        return False

    key = "exclude_shape" if negate else "shape"
    filters.setdefault(key, [])
    if preset not in filters[key]:
        filters[key].append(preset)
    return True


def add_post_id_filter(filters: dict[str, Any], value: str, negate: bool = False) -> bool:
    match = re.fullmatch(r"#?(\d+)", value.strip())
    if not match:
        return False

    key = "exclude_danbooru_post_id" if negate else "danbooru_post_id"
    filters.setdefault(key, [])
    filters[key].append(int(match.group(1)))
    return True


def add_filename_filter(filters: dict[str, Any], value: str, negate: bool = False) -> bool:
    filename = value.strip().strip("\"'").strip()
    if not filename:
        return False
    key = "exclude_filename" if negate else "filename"
    filters.setdefault(key, [])
    filters[key].append(filename)
    return True


def parse_search_terms(
    raw: str,
) -> tuple[list[tuple[str | None, str]], list[tuple[str | None, str]], dict[str, Any]]:
    include_tags: list[tuple[str | None, str]] = []
    exclude_tags: list[tuple[str | None, str]] = []
    filters: dict[str, Any] = {}

    for term in normalize_search_phrases(raw).split():
        term = term.strip().strip("\"'")
        if not term:
            continue
        negate = term.startswith("-")
        if negate:
            term = term[1:]
        lowered = term.lower()

        if add_post_id_filter(filters, term, negate):
            continue

        if add_dimension_filter(filters, term):
            continue

        if add_shape_filter(filters, term, negate):
            continue

        if BARE_FILENAME_RE.fullmatch(term) and add_filename_filter(filters, term, negate):
            continue

        if ":" in term:
            prefix, value = term.split(":", 1)
            prefix = prefix.lower()
            if prefix in POST_ID_FILTER_PREFIXES and add_post_id_filter(filters, value, negate):
                continue
            if prefix in SHAPE_FILTER_PREFIXES and add_shape_filter(filters, value, negate):
                continue
            if prefix in FILENAME_FILTER_PREFIXES and add_filename_filter(filters, value, negate):
                continue
            if prefix == "rating":
                filters["rating"] = value
                continue
            if prefix == "ext":
                filters["ext"] = value.lower().lstrip(".")
                continue
            if prefix == "folder":
                filters["folder"] = value
                continue
            if prefix == "orientation":
                filters["orientation"] = value.lower()
                continue
            if prefix in DATE_FILTER_PREFIXES:
                filters.setdefault(DATE_FILTER_PREFIXES[prefix], [])
                filters[DATE_FILTER_PREFIXES[prefix]].append(value)
                continue
            if prefix in DIMENSION_FILTER_PREFIXES and add_dimension_filter(filters, value):
                continue
            if prefix in HEART_SPAM_FILTER_PREFIXES:
                filters.setdefault("heart_spam", [])
                filters["heart_spam"].append(value)
                continue
            if prefix in NUMERIC_FILTERS:
                filters.setdefault(prefix, [])
                filters[prefix].append(value)
                continue
            if prefix == USER_TAG_CATEGORY:
                (exclude_tags if negate else include_tags).append((USER_TAG_CATEGORY, normalize_user_tag(value)))
                continue
            if prefix in TAG_CATEGORIES:
                (exclude_tags if negate else include_tags).append((prefix, normalize_search_tag(value)))
                continue

        (exclude_tags if negate else include_tags).append((None, lowered))

    return include_tags, exclude_tags, filters


def search_has_post_id_filter(raw: str) -> bool:
    if not raw.strip():
        return False
    _, _, filters = parse_search_terms(raw.strip())
    return bool(filters.get("danbooru_post_id"))


def combined_image_search(
    q: str,
    folder: str | None = None,
    rating: str | None = None,
) -> tuple[str, bool, str | None]:
    search = q.strip()
    exact_post_id = search_has_post_id_filter(search)
    selected_root_id: str | None = None
    if not exact_post_id:
        if folder:
            if folder.startswith("@root/"):
                selected_root_id = folder[len("@root/"):]
            else:
                search += f" folder:{folder}"
        if rating:
            search += f" rating:{rating}"
    return search, exact_post_id, selected_root_id


def search_requires_user_db(
    include_tags: list[tuple[str | None, str]],
    exclude_tags: list[tuple[str | None, str]],
    filters: dict[str, Any],
) -> bool:
    return bool(include_tags or exclude_tags or filters.get("heart_spam"))


def _add_numeric(where: list[str], params: list[Any], expr: str, raw: str) -> None:
    m = re.fullmatch(r"\s*(>=|<=|>|<|=)?\s*(\d+(?:\.\d+)?)\s*", raw.strip("\"'"))
    if not m:
        return
    op = m.group(1) or ">="
    where.append(f"{expr} {op} ?")
    params.append(float(m.group(2)))


def _date_filter_value(raw: str) -> str:
    lowered = raw.strip().lower()
    if lowered == "today":
        return date.today().isoformat()
    if lowered == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    return raw.strip()


def _filename_like_value(value: str) -> str:
    escaped = value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _add_date_filter(where: list[str], params: list[Any], expr: str, raw: str) -> None:
    value = raw.strip().strip("\"'")
    if not value:
        return
    if ".." in value:
        start, end = value.split("..", 1)
        if start.strip():
            where.append(f"date({expr}) >= date(?)")
            params.append(_date_filter_value(start))
        if end.strip():
            where.append(f"date({expr}) <= date(?)")
            params.append(_date_filter_value(end))
        return

    m = re.fullmatch(r"\s*(>=|<=|>|<|=)?\s*(.+?)\s*", value)
    if not m:
        return
    op = m.group(1) or "="
    where.append(f"date({expr}) {op} date(?)")
    params.append(_date_filter_value(m.group(2)))


def shape_filter_clause(preset: str) -> str | None:
    ratio_expr = "(CAST(p.width AS REAL)/NULLIF(p.height, 0))"
    if preset == "vertical":
        return "p.height > p.width"
    if preset == "horizontal":
        return "p.width > p.height"
    if preset == "phone":
        return f"p.height > p.width AND p.height >= 1280 AND {ratio_expr} BETWEEN 0.45 AND 0.75"
    if preset == "banner":
        return f"p.width >= 1200 AND {ratio_expr} >= 1.8"
    if preset == "logo":
        return f"{ratio_expr} BETWEEN 0.75 AND 1.35"
    return None


def build_where(
    include_tags: list[tuple[str | None, str]],
    exclude_tags: list[tuple[str | None, str]],
    filters: dict[str, Any],
) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []

    def tag_condition(cat: str | None, name: str) -> str:
        clauses: list[str] = []
        if cat != USER_TAG_CATEGORY:
            parts = ["EXISTS (SELECT 1 FROM post_tags pt JOIN tags t ON t.id=pt.tag_id WHERE pt.post_id=p.id AND t.name=?"]
            params.append(name)
            if cat:
                parts.append("AND t.category=?")
                params.append(cat)
            parts.append(")")
            clauses.append(" ".join(parts))
        if cat is None or cat == USER_TAG_CATEGORY or cat in TAG_CATEGORIES:
            user_parts = [
                f"EXISTS (SELECT 1 FROM userdb.user_image_tags uit WHERE {user_file_match('uit')} AND uit.tag_name=?"
            ]
            params.append(name)
            if cat in TAG_CATEGORIES:
                user_parts.append("AND uit.tag_category=?")
                params.append(cat)
            user_parts.append(")")
            clauses.append(" ".join(user_parts))
        return "(" + " OR ".join(clauses) + ")"

    for cat, name in include_tags:
        where.append(tag_condition(cat, name))

    for cat, name in exclude_tags:
        where.append(f"NOT {tag_condition(cat, name)}")

    if ratings := normalize_rating_values(str(filters.get("rating") or "")):
        placeholders = ",".join("?" for _ in ratings)
        where.append(f"COALESCE(NULLIF(p.rating, ''), 'u') IN ({placeholders})")
        params.extend(ratings)
    if e := filters.get("ext"):
        where.append("f.ext=?")
        params.append(e)
    if fo := filters.get("folder"):
        where.append("f.folder LIKE ?")
        params.append(f"%{fo}%")
    if root_id := filters.get("root_id"):
        where.append("f.root_id=?")
        params.append(root_id)
    for filename in filters.get("filename", []):
        where.append("LOWER(f.name) LIKE ? ESCAPE '\\'")
        params.append(_filename_like_value(str(filename)))
    for filename in filters.get("exclude_filename", []):
        where.append("LOWER(f.name) NOT LIKE ? ESCAPE '\\'")
        params.append(_filename_like_value(str(filename)))

    if ids := filters.get("danbooru_post_id"):
        placeholders = ",".join("?" for _ in ids)
        where.append(f"p.danbooru_post_id IN ({placeholders})")
        params.extend(ids)
    if excluded_ids := filters.get("exclude_danbooru_post_id"):
        placeholders = ",".join("?" for _ in excluded_ids)
        where.append(f"(p.danbooru_post_id IS NULL OR p.danbooru_post_id NOT IN ({placeholders}))")
        params.extend(excluded_ids)

    for v in filters.get("uploaded", []):
        _add_date_filter(where, params, "p.created_at", v)
    for v in filters.get("downloaded", []):
        _add_date_filter(where, params, "f.downloaded_at", v)

    for v in filters.get("width", []) or filters.get("w", []):
        _add_numeric(where, params, "p.width", v)
    for v in filters.get("height", []) or filters.get("h", []):
        _add_numeric(where, params, "p.height", v)
    for v in filters.get("pixels", []) or filters.get("mp", []):
        _add_numeric(where, params, "(p.width*p.height)", v)
    for v in filters.get("ratio", []):
        _add_numeric(where, params, "(CAST(p.width AS REAL)/NULLIF(p.height,0))", v)
    for v in filters.get("score", []):
        _add_numeric(where, params, "p.score", v)
    for v in filters.get("heart_spam", []):
        _add_numeric(
            where,
            params,
            f"COALESCE((SELECT MAX(iv_heart.heart_spam_count) FROM userdb.image_views iv_heart WHERE {user_file_match('iv_heart')}), 0)",
            v,
        )

    orient = filters.get("orientation")
    if orient in ("portrait", "vertical"):
        where.append("p.height > p.width")
    elif orient in ("landscape", "horizontal"):
        where.append("p.width > p.height")
    elif orient == "square":
        where.append("p.width = p.height")

    for preset in filters.get("shape", []):
        clause = shape_filter_clause(preset)
        if clause:
            where.append(f"({clause})")
    for preset in filters.get("exclude_shape", []):
        clause = shape_filter_clause(preset)
        if clause:
            where.append(f"NOT ({clause})")

    sql = f"WHERE {' AND '.join(where)}" if where else ""
    return sql, params


def add_where_clause(where_sql: str, clause: str) -> str:
    if where_sql:
        return f"{where_sql} AND {clause}"
    return f"WHERE {clause}"
