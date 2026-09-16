"""Danbooru tag wiki and artist metadata: fetch, parse, and cache.

Moved verbatim from ``core.py``. Owns the DText parsing rules, the wiki/artist
lookups against the Danbooru API, and the ``tag_wiki_cache`` table in the shared
user database. Fetching is explicit and cached; nothing here downloads media.

No ``core`` import: every dependency resolves to a real owner.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException

from database import get_data_db
from modules.danbooru.models import ArtistUrl, RelatedImageInfo, TagWikiExample, TagWikiInfo, TagWikiSection, TagWikiTextLine, TagWikiTextPart
from modules.danbooru.client import DANBOORU_POST_URL_PREFIX, danbooru_json
from modules.danbooru.relations import related_infos_for_danbooru_ids
from modules.danbooru.tag_names import normalize_search_tag
from services.value_helpers import int_or_none, unique_ints


TAG_WIKI_CACHE_MAX_AGE = timedelta(days=30)
DTEXT_HEADING_RE = re.compile(r"^h[1-6]\.\s+(.+?)\s*$")
DTEXT_TOKEN_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]*))?\]\]|!post\s+#?(\d+):?", re.IGNORECASE)
DTEXT_EXAMPLE_POST_RE = re.compile(r"!post\s+#?(\d+)", re.IGNORECASE)
DTEXT_EXTERNAL_LINK_RE = re.compile(r'"([^"]+)":\[[^\]]+\]')


def json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if item is not None and str(item).strip()]


def unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def artist_urls_from_json(value: str | None) -> list[ArtistUrl]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    urls: list[ArtistUrl] = []
    for item in loaded:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            if url:
                urls.append(ArtistUrl(url=url, is_active=bool(item.get("is_active", True))))
        elif item is not None:
            url = str(item).strip()
            if url:
                urls.append(ArtistUrl(url=url))
    return urls


def wiki_link_display(target: str, label: str | None) -> str:
    if label is not None and label.strip():
        return label.strip().replace("_", " ")
    display = target.strip().replace("_", " ")
    return re.sub(r"\s+\([^)]+\)$", "", display).strip() or display


def clean_wiki_text(raw: str) -> str:
    value = raw
    value = DTEXT_EXTERNAL_LINK_RE.sub(r"\1", value)
    value = re.sub(r"\[/?(?:b|i|u|s|tn)\]", "", value, flags=re.IGNORECASE)
    value = value.replace("[[", "").replace("]]", "")
    return value


def wiki_text_line(raw: str) -> TagWikiTextLine:
    parts: list[TagWikiTextPart] = []
    position = 0
    for match in DTEXT_TOKEN_RE.finditer(raw):
        if match.start() > position:
            text = clean_wiki_text(raw[position:match.start()])
            if text:
                parts.append(TagWikiTextPart(text=text))
        if match.group(3):
            post_id = int_or_none(match.group(3))
            if post_id is not None:
                parts.append(TagWikiTextPart(text=f"#{post_id}", post_id=post_id))
        else:
            target = match.group(1).strip()
            label = match.group(2)
            parts.append(
                TagWikiTextPart(
                    text=wiki_link_display(target, label),
                    tag=normalize_search_tag(target),
                )
            )
        position = match.end()
    if position < len(raw):
        text = clean_wiki_text(raw[position:])
        if text:
            parts.append(TagWikiTextPart(text=text))
    if not parts:
        parts.append(TagWikiTextPart(text=clean_wiki_text(raw)))
    return TagWikiTextLine(parts=parts)


def wiki_paragraphs(lines: list[str]) -> list[TagWikiTextLine]:
    paragraphs: list[TagWikiTextLine] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(wiki_text_line(" ".join(current)))
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(wiki_text_line(" ".join(current)))
    return paragraphs


def parse_tag_wiki_body(body: str) -> tuple[list[TagWikiTextLine], list[int], list[TagWikiSection]]:
    intro_lines: list[str] = []
    raw_sections: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in body.splitlines():
        heading = DTEXT_HEADING_RE.match(line.strip())
        if heading:
            if current_title is None:
                intro_lines = current_lines
            else:
                raw_sections.append((current_title, current_lines))
            current_title = heading.group(1).strip()
            current_lines = []
            continue
        current_lines.append(line)

    if current_title is None:
        intro_lines = current_lines
    else:
        raw_sections.append((current_title, current_lines))

    examples: list[int] = []
    sections: list[TagWikiSection] = []
    for title, lines in raw_sections:
        if title.strip().lower() == "examples":
            for line in lines:
                for match in DTEXT_EXAMPLE_POST_RE.finditer(line):
                    post_id = int_or_none(match.group(1))
                    if post_id is not None and post_id not in examples:
                        examples.append(post_id)
            continue

        paragraphs: list[TagWikiTextLine] = []
        items: list[TagWikiTextLine] = []
        paragraph_buffer: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if paragraph_buffer:
                    paragraphs.append(wiki_text_line(" ".join(paragraph_buffer)))
                    paragraph_buffer = []
                continue
            if stripped.startswith("*"):
                if paragraph_buffer:
                    paragraphs.append(wiki_text_line(" ".join(paragraph_buffer)))
                    paragraph_buffer = []
                items.append(wiki_text_line(stripped.lstrip("*").strip()))
            else:
                paragraph_buffer.append(stripped)
        if paragraph_buffer:
            paragraphs.append(wiki_text_line(" ".join(paragraph_buffer)))

        if paragraphs or items:
            sections.append(TagWikiSection(title=title, paragraphs=paragraphs, items=items))

    return wiki_paragraphs(intro_lines), examples, sections


def tag_wiki_example(post_id: int, local_infos: dict[int, RelatedImageInfo]) -> TagWikiExample:
    local_info = local_infos.get(post_id)
    if local_info:
        data = local_info.model_dump() if hasattr(local_info, "model_dump") else local_info.dict()
        return TagWikiExample(**data)
    return TagWikiExample(
        danbooru_post_id=post_id,
        post_url=f"{DANBOORU_POST_URL_PREFIX}{post_id}",
    )


def post_ids_from_wiki_lines(lines: list[TagWikiTextLine]) -> list[int]:
    ids: list[int] = []
    for line in lines:
        for part in line.parts:
            if part.post_id is not None:
                ids.append(part.post_id)
    return unique_ints(ids)


def post_ids_from_wiki_sections(sections: list[TagWikiSection]) -> list[int]:
    ids: list[int] = []
    for section in sections:
        ids.extend(post_ids_from_wiki_lines(section.paragraphs))
        ids.extend(post_ids_from_wiki_lines(section.items))
    return unique_ints(ids)


def tag_wiki_info_from_values(
    tag_name: str,
    title: str,
    other_names: list[str],
    body: str,
    aliases: list[str],
    implications: list[str],
    artist_id: int | None,
    artist_name: str | None,
    artist_group_name: str | None,
    artist_urls: list[ArtistUrl],
    status: str,
    cached_at: str | None,
    error: str | None = None,
) -> TagWikiInfo:
    description, example_ids, sections = parse_tag_wiki_body(body)
    post_reference_ids = unique_ints([
        *example_ids,
        *post_ids_from_wiki_lines(description),
        *post_ids_from_wiki_sections(sections),
    ])
    local_infos: dict[int, RelatedImageInfo] = {}
    if post_reference_ids:
        with get_data_db() as conn:
            local_infos = related_infos_for_danbooru_ids(conn, post_reference_ids)
    return TagWikiInfo(
        tag_name=tag_name,
        title=title or tag_name,
        other_names=other_names,
        description=description,
        examples=[tag_wiki_example(post_id, local_infos) for post_id in example_ids],
        post_references=[tag_wiki_example(post_id, local_infos) for post_id in post_reference_ids],
        sections=sections,
        aliases=aliases,
        implications=implications,
        artist_id=artist_id,
        artist_name=artist_name,
        artist_group_name=artist_group_name,
        artist_urls=artist_urls,
        available=status == "ok",
        cached_at=cached_at,
        error=error,
    )


def tag_wiki_info_from_cache_row(tag_name: str, row: dict[str, Any], error: str | None = None) -> TagWikiInfo:
    return tag_wiki_info_from_values(
        tag_name=tag_name,
        title=row["title"],
        other_names=json_list(row.get("other_names_json")),
        body=row.get("body") or "",
        aliases=json_list(row.get("aliases_json")),
        implications=json_list(row.get("implications_json")),
        artist_id=int_or_none(row.get("artist_id")),
        artist_name=row.get("artist_name"),
        artist_group_name=row.get("artist_group_name"),
        artist_urls=artist_urls_from_json(row.get("artist_urls_json")),
        status=row.get("status") or "missing",
        cached_at=row.get("fetched_at"),
        error=error or row.get("error"),
    )


def tag_wiki_cache_fresh(row: dict[str, Any]) -> bool:
    try:
        fetched = datetime.fromisoformat(str(row.get("fetched_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return datetime.now(fetched.tzinfo) - fetched < TAG_WIKI_CACHE_MAX_AGE


def tag_wiki_cache_complete_for_category(row: dict[str, Any], category: str | None) -> bool:
    if category != "artist":
        return True
    if row.get("artist_id") is None:
        return False
    return bool(row.get("artist_urls_checked"))


def danbooru_related_tag_names(endpoint: str, params: dict[str, str | int], field: str) -> list[str]:
    try:
        data = danbooru_json(
            endpoint,
            {
                **params,
                "search[status]": "active",
                "limit": 100,
                "only": f"{field},status",
            },
        )
    except HTTPException:
        return []
    if not isinstance(data, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        name = str(row.get(field) or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def normalized_artist_urls(row: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_url(raw_url: Any, is_active: bool = True) -> None:
        url = str(raw_url or "").strip()
        if not url:
            return
        key = url.casefold()
        if key in seen:
            return
        seen.add(key)
        result.append({"url": url, "is_active": is_active})

    raw_urls = row.get("urls")
    if isinstance(raw_urls, list):
        for item in raw_urls:
            if isinstance(item, dict):
                active = True
                if "is_active" in item:
                    active = bool(item.get("is_active"))
                if item.get("is_deleted") is True or item.get("status") == "deleted":
                    active = False
                add_url(item.get("url") or item.get("normalized_url"), active)
            else:
                add_url(item)

    raw_url_string = str(row.get("url_string") or "").strip()
    if raw_url_string:
        for url in re.split(r"[\r\n\s]+", raw_url_string):
            add_url(url)

    return result


def merge_artist_url_rows(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            key = url.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append({"url": url, "is_active": bool(item.get("is_active", True))})
    return result


def fetch_artist_values(tag_name: str) -> dict[str, Any]:
    try:
        data = danbooru_json(
            "/artists.json",
            {
                "search[name]": tag_name,
                "limit": 1,
            },
        )
    except HTTPException:
        return {
            "artist_id": None,
            "artist_name": None,
            "artist_group_name": None,
            "artist_urls": [],
            "artist_other_names": [],
            "artist_urls_checked": False,
            "artist_available": False,
        }

    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return {
            "artist_id": None,
            "artist_name": None,
            "artist_group_name": None,
            "artist_urls": [],
            "artist_other_names": [],
            "artist_urls_checked": False,
            "artist_available": False,
        }

    row = data[0]
    other_names = row.get("other_names")
    if not isinstance(other_names, list):
        other_names = []
    artist_name = str(row.get("name") or tag_name).strip() or tag_name
    group_name = str(row.get("group_name") or "").strip() or None
    artist_id = int_or_none(row.get("id"))
    url_groups = [normalized_artist_urls(row)]
    if artist_id is not None:
        try:
            artist_url_rows = danbooru_json(
                "/artist_urls.json",
                {
                    "search[artist_id]": artist_id,
                    "limit": 100,
                },
            )
        except HTTPException:
            artist_url_rows = []
        if isinstance(artist_url_rows, list):
            url_groups.append(normalized_artist_urls({"urls": artist_url_rows}))
    urls = merge_artist_url_rows(url_groups)

    return {
        "artist_id": artist_id,
        "artist_name": artist_name,
        "artist_group_name": group_name,
        "artist_urls": urls,
        "artist_other_names": unique_strings(other_names),
        "artist_urls_checked": True,
        "artist_available": bool(artist_name or group_name or urls),
    }


def fetch_tag_wiki_values(tag_name: str, category: str | None = None) -> dict[str, Any]:
    title = urllib.parse.quote(tag_name, safe="")
    page: dict[str, Any] | None = None
    try:
        payload = danbooru_json(f"/wiki_pages/{title}.json", {})
        if not isinstance(payload, dict):
            raise HTTPException(502, "Unexpected Danbooru wiki payload")
        page = payload
    except HTTPException as exc:
        if exc.status_code != 404:
            raise

    other_names: list[str] = []
    body = ""
    page_title = tag_name
    if page is not None:
        raw_other_names = page.get("other_names")
        if isinstance(raw_other_names, list):
            other_names = [str(name) for name in raw_other_names if str(name).strip()]
        body = str(page.get("body") or "")
        page_title = str(page.get("title") or tag_name)

    aliases = danbooru_related_tag_names(
        "/tag_aliases.json",
        {"search[consequent_name]": tag_name},
        "antecedent_name",
    )
    implications = danbooru_related_tag_names(
        "/tag_implications.json",
        {"search[antecedent_name]": tag_name},
        "consequent_name",
    )
    artist = fetch_artist_values(tag_name) if category == "artist" else {
        "artist_id": None,
        "artist_name": None,
        "artist_group_name": None,
        "artist_urls": [],
        "artist_other_names": [],
        "artist_urls_checked": False,
        "artist_available": False,
    }
    merged_other_names = unique_strings([*other_names, *artist["artist_other_names"]])
    artist_available = bool(artist["artist_available"])
    wiki_available = page is not None

    return {
        "title": page_title if wiki_available else (artist["artist_name"] or tag_name),
        "other_names": merged_other_names,
        "body": body,
        "aliases": aliases,
        "implications": implications,
        "artist_id": artist["artist_id"],
        "artist_name": artist["artist_name"],
        "artist_group_name": artist["artist_group_name"],
        "artist_urls": artist["artist_urls"],
        "artist_urls_checked": artist["artist_urls_checked"],
        "status": "ok" if wiki_available or artist_available else "missing",
        "error": None,
    }


def save_tag_wiki_cache(conn, tag_name: str, values: dict[str, Any]) -> dict[str, Any]:
    fetched_at = datetime.now().isoformat(timespec="seconds")
    row = {
        "title": values.get("title") or tag_name,
        "other_names_json": json.dumps(values.get("other_names") or [], ensure_ascii=False),
        "body": values.get("body") or "",
        "aliases_json": json.dumps(values.get("aliases") or [], ensure_ascii=False),
        "implications_json": json.dumps(values.get("implications") or [], ensure_ascii=False),
        "artist_id": values.get("artist_id"),
        "artist_name": values.get("artist_name"),
        "artist_group_name": values.get("artist_group_name"),
        "artist_urls_json": json.dumps(values.get("artist_urls") or [], ensure_ascii=False),
        "artist_urls_checked": 1 if values.get("artist_urls_checked") else 0,
        "status": values.get("status") or "missing",
        "error": values.get("error"),
        "fetched_at": fetched_at,
    }
    conn.execute(
        """
        INSERT INTO tag_wiki_cache (
            tag_name, title, other_names_json, body, aliases_json, implications_json,
            artist_id, artist_name, artist_group_name, artist_urls_json, artist_urls_checked,
            status, error, fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tag_name) DO UPDATE SET
            title=excluded.title,
            other_names_json=excluded.other_names_json,
            body=excluded.body,
            aliases_json=excluded.aliases_json,
            implications_json=excluded.implications_json,
            artist_id=excluded.artist_id,
            artist_name=excluded.artist_name,
            artist_group_name=excluded.artist_group_name,
            artist_urls_json=excluded.artist_urls_json,
            artist_urls_checked=excluded.artist_urls_checked,
            status=excluded.status,
            error=excluded.error,
            fetched_at=excluded.fetched_at
        """,
        (
            tag_name,
            row["title"],
            row["other_names_json"],
            row["body"],
            row["aliases_json"],
            row["implications_json"],
            row["artist_id"],
            row["artist_name"],
            row["artist_group_name"],
            row["artist_urls_json"],
            row["artist_urls_checked"],
            row["status"],
            row["error"],
            row["fetched_at"],
        ),
    )
    conn.commit()
    return row
