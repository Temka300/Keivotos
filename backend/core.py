from __future__ import annotations

import asyncio
import base64
import copy
import json
import hashlib
import io
import logging
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Iterable

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from PIL import Image

from automation import automation_loop
from local_recovery import create_local_recovery_checkpoint
from credentials import (
    clear_credentials,
    credential_environment,
    credentials_status,
    effective_credentials,
    save_credentials,
)
from database import get_data_db, get_user_db, init_data_db, init_user_db
from models import (
    ArtistUrl,
    ArtistFollowCheckResult,
    ArtistFollowInfo,
    ArtistProfileArchiveResult,
    ArtistProfileAsset,
    ArtistProfileBulkArchiveResult,
    CollectionCreate,
    CollectionInfo,
    CollectionItemsUpdate,
    CollectionMembershipRequest,
    CollectionPreviewItem,
    CollectionUpdate,
    DailyChallenge,
    DailyChallengeClues,
    DailyChallengeImage,
    DailyChallengeOption,
    DanbooruCredentialsUpdate,
    DanbooruCredentialStatus,
    BackfillToolRequest,
    FavoriteTagComboCreate,
    FavoriteTagComboInfo,
    FavoriteBatchUpdate,
    FolderCreate,
    FolderInfo,
    HomeImageRail,
    HomeImageRailItem,
    HomeImageRails,
    HomeCoverCandidate,
    HomeTagInfo,
    HomeTags,
    ImageDetail,
    ImageBatchMove,
    ImageMoveFolder,
    ImageSummary,
    PaginatedImages,
    PaginatedTags,
    PopularityPeriod,
    ImageRelations,
    RelatedImageInfo,
    Stats,
    TagWikiExample,
    TagWikiInfo,
    TagWikiSection,
    TagWikiTextLine,
    TagWikiTextPart,
    ToolInfo,
    ToolFolderInfo,
    ToolRunResult,
    ToolStatusInfo,
    TagInfo,
    TimelapseFrames,
    UserImageTagCreate,
)
from thumbnails import DEFAULT_THUMB_SIZE, ensure_thumbnail, thumbnail_cache_token
from config import (
    ARTIST_PROFILE_ARCHIVE_DIR,
    DATA_DB_PATH,
    DATA_ROOT,
    DANBOORU_MODULE,
    DANBOORU_SLUG,
    GALLERY_DL_DIR,
    METADATA_DIR,
    MODULE_REGISTRY,
    SCAN_FOLDERS,
    SIDECAR_DIR,
    USER_DB_PATH,
    migrate_legacy_default_metadata,
    promote_legacy_module_backups,
    promote_user_database,
)
import suite_modules
from product import DISPLAY_NAME, VERSION
from security import validate_local_browser_request
from storage_layout import (
    LibraryRoot,
    SIDECAR_SUFFIXES,
    canonical_sidecar_path as layout_sidecar_path,
    identity_for_media,
    migrate_existing_sidecars,
    sidecar_candidates as layout_sidecar_candidates,
)
from services.query_helpers import (
    RATING_QUERY_PATTERN,
    RATING_VALUES,
    normalize_rating_values,
    user_file_lookup_params,
    user_file_lookup_sql,
    user_file_match,
)
# Extracted services and module code. Imported here so `from core import *` keeps
# supplying these names to routers that have not been migrated to explicit
# imports yet; each name is the same object it always was.
from services.tag_names import (
    TAG_CATEGORIES,
    normalize_search_tag,
    normalize_user_tag,
    normalize_user_tag_category,
)
from services.value_helpers import int_or_none, unique_ints
from modules.danbooru.artist_profiles import (
    ARTIST_PROFILE_ALLOWED_IMAGE_HOSTS,
    ARTIST_PROFILE_MAX_BYTES,
    TWITTER_RESERVED_PATHS,
    archive_artist_profile_asset,
    archive_artist_profile_media,
    artist_profile_asset_from_row,
    artist_profile_sources,
    cached_artist_profile_urls,
    download_artist_profile_image,
    gallery_dl_command,
    gallery_dl_twitter_profile_media,
    list_artist_profile_assets_from_conn,
    pixiv_profile_media,
    twitter_profile_media_from_messages,
)
from modules.danbooru.artist_follows import (
    ARTIST_FOLLOW_POST_LIMIT,
    artist_follow_info_from_row,
    artist_follow_local_count,
    artist_follow_posts,
    artist_follow_profile_post,
    fetch_artist_danbooru_post_ids,
    load_artist_follow,
    seed_artist_follow_posts_from_cache,
)
from modules.danbooru.tag_wiki import (
    DTEXT_EXAMPLE_POST_RE,
    DTEXT_EXTERNAL_LINK_RE,
    DTEXT_HEADING_RE,
    DTEXT_TOKEN_RE,
    TAG_WIKI_CACHE_MAX_AGE,
    artist_urls_from_json,
    clean_wiki_text,
    danbooru_related_tag_names,
    fetch_artist_values,
    fetch_tag_wiki_values,
    json_list,
    merge_artist_url_rows,
    normalized_artist_urls,
    parse_tag_wiki_body,
    post_ids_from_wiki_lines,
    post_ids_from_wiki_sections,
    save_tag_wiki_cache,
    tag_wiki_cache_complete_for_category,
    tag_wiki_cache_fresh,
    tag_wiki_example,
    tag_wiki_info_from_cache_row,
    tag_wiki_info_from_values,
    unique_strings,
    wiki_link_display,
    wiki_paragraphs,
    wiki_text_line,
)
from modules.danbooru.tags import (
    list_user_tags,
)
from modules.danbooru.client import (
    DANBOORU_POST_URL_PREFIX,
    USER_AGENT,
    danbooru_json,
    normalize_danbooru_post_payload,
)
from modules.danbooru.relations import (
    related_info_for_id,
    related_info_from_row,
    related_infos_for_danbooru_ids,
)
from services.collections import (
    collection_preview_items_from_rows,
    load_collection_info,
)
from services.profile import profile_asset, profile_asset_token
from services.user_library import (
    _combo_from_row,
    _combo_key,
    _combo_name,
    _normalize_combo_tags,
    _normalize_tag_name,
)

logger = logging.getLogger(__name__)


COPY_SUFFIX_RE = re.compile(r"\s+\(\d+\)(?=\.[^.]+$)")
STREAM_CHUNK_SIZE = 1024 * 1024
def duplicate_filename_key(filename: str | None) -> str:
    if not filename:
        return ""
    return COPY_SUFFIX_RE.sub("", filename).casefold()


def duplicate_group_expr(alias: str) -> str:
    return f"COALESCE(NULLIF({alias}.local_md5, ''), duplicate_key({alias}.name))"


def duplicate_filter_sql(scope: str) -> str:
    group_expr = duplicate_group_expr("f")
    inner_expr = duplicate_group_expr("df")
    folder_identity = "COALESCE(NULLIF(f.root_id, ''), f.folder, '')"
    inner_folder_identity = "COALESCE(NULLIF(df.root_id, ''), df.folder, '')"
    if scope == "same_folder":
        return f"""({group_expr} || char(31) || {folder_identity}) IN (
            SELECT {inner_expr} || char(31) || {inner_folder_identity}
            FROM files df
            GROUP BY {inner_expr}, {inner_folder_identity}
            HAVING COUNT(*) > 1
        )"""
    if scope == "different_folder":
        return f"""{group_expr} IN (
            SELECT {inner_expr}
            FROM files df
            GROUP BY {inner_expr}
            HAVING COUNT(DISTINCT {inner_folder_identity}) > 1
        )"""
    return f"""{group_expr} IN (
        SELECT {inner_expr}
        FROM files df
        GROUP BY {inner_expr}
        HAVING COUNT(*) > 1
    )"""


def media_placeholder(ext: str | None) -> Response:
    label = (ext or "file").upper().lstrip(".")[:6]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300">
  <rect width="300" height="300" fill="#1e1e2e"/>
  <rect x="74" y="104" width="152" height="92" rx="12" fill="#2a2a3a"/>
  <path d="M132 126v48l42-24z" fill="#9ca3af"/>
  <text x="150" y="218" text-anchor="middle" font-family="system-ui, sans-serif" font-size="24" font-weight="700" fill="#9ca3af">{label}</text>
</svg>"""
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    if not range_header or not range_header.startswith("bytes="):
        return None
    range_value = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
    if "-" not in range_value:
        return None

    start_text, end_text = range_value.split("-", 1)
    try:
        if start_text == "":
            suffix_length = int(end_text)
            if suffix_length <= 0:
                return None
            return max(file_size - suffix_length, 0), file_size - 1

        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1
    except ValueError:
        return None

    if start < 0 or start >= file_size or end < start:
        return None
    return start, min(end, file_size - 1)


def file_range_iter(path: Path, start: int, end: int):
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(STREAM_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def registered_folder_rows() -> list[dict[str, Any]]:
    with get_user_db() as uconn:
        return uconn.execute(
            """SELECT name AS registration_key,
                      COALESCE(NULLIF(display_name, ''), name) AS name,
                      path, root_id
                 FROM registered_folders"""
        ).fetchall()


def library_roots() -> list[LibraryRoot]:
    return [
        LibraryRoot(str(row["root_id"]), str(row["name"]), Path(row["path"]).resolve(strict=False))
        for row in registered_folder_rows()
        if row.get("root_id") and row.get("path")
    ]


def registered_folder_path(folder_name: str) -> Path | None:
    with get_user_db() as uconn:
        row = uconn.execute(
            """SELECT path FROM registered_folders
                WHERE root_id=? OR name=? OR display_name=?
                ORDER BY CASE WHEN root_id=? THEN 0 WHEN name=? THEN 1 ELSE 2 END
                LIMIT 1""",
            (folder_name, folder_name, folder_name, folder_name, folder_name),
        ).fetchone()
    if row and row["path"]:
        return Path(row["path"])
    return None


def ensure_managed_path(path: Path, action: str) -> None:
    """Allow file operations inside the data root or any registered folder."""
    resolved = path.resolve(strict=False)
    roots = [DATA_ROOT.resolve(strict=False)]
    for row in registered_folder_rows():
        if row["path"]:
            roots.append(Path(row["path"]).resolve(strict=False))
    for root in roots:
        try:
            resolved.relative_to(root)
            return
        except ValueError:
            continue
    raise HTTPException(400, f"Refusing to {action} a file outside the library folders")


def folder_target(folder: str) -> tuple[Path, str | None]:
    name = folder.strip().strip("/\\")
    if not name or name.lower() == "root":
        return DATA_ROOT, None

    root_selector_prefix = "@root/"
    if name.startswith(root_selector_prefix):
        root_id = name[len(root_selector_prefix):]
        if not root_id or "/" in root_id or "\\" in root_id:
            raise HTTPException(400, "Invalid library root identity")
        with get_user_db() as uconn:
            row = uconn.execute(
                """SELECT COALESCE(NULLIF(display_name, ''), name) AS display_name, path
                     FROM registered_folders WHERE root_id=?""",
                (root_id,),
            ).fetchone()
        if not row or not row.get("path"):
            raise HTTPException(404, "Registered folder was not found")
        return Path(row["path"]).resolve(strict=False), str(row["display_name"])

    candidate = Path(name)
    if candidate.is_absolute() or candidate.drive or any(part in ("", ".", "..") for part in candidate.parts):
        raise HTTPException(400, "Invalid folder name")

    # Registered folders may live outside the data root; map the folder label
    # (registered name, optionally with a subpath) onto the registered path.
    base_path = registered_folder_path(name)
    subpath = Path()
    if base_path is None and len(candidate.parts) > 1:
        base_path = registered_folder_path(candidate.parts[0])
        subpath = Path(*candidate.parts[1:])
    if base_path is not None:
        resolved_base = base_path.resolve(strict=False)
        resolved_root = DATA_ROOT.resolve(strict=False)
        try:
            resolved_base.relative_to(resolved_root)
        except ValueError:
            target_dir = (resolved_base / subpath).resolve(strict=False)
            try:
                target_dir.relative_to(resolved_base)
            except ValueError:
                raise HTTPException(400, "Target folder must stay inside the registered folder")
            return target_dir, name

    target_dir = (DATA_ROOT / candidate).resolve(strict=False)
    try:
        relative_folder = str(target_dir.relative_to(DATA_ROOT.resolve(strict=False)))
    except ValueError:
        raise HTTPException(400, "Target folder must be inside the data root")

    return target_dir, relative_folder


def move_payload_text(payload_text: str | None, target_path: Path) -> str | None:
    if not payload_text:
        return None
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return None

    local_file = payload.setdefault("local_file", {})
    if isinstance(local_file, dict):
        local_file["path"] = str(target_path)
        local_file["name"] = target_path.name
        try:
            local_file["size"] = target_path.stat().st_size
        except OSError:
            pass
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def rewrite_json_sidecar(sidecar_path: Path, target_path: Path) -> str | None:
    if not sidecar_path.exists():
        return None
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    local_file = payload.setdefault("local_file", {})
    if isinstance(local_file, dict):
        local_file["path"] = str(target_path)
        local_file["name"] = target_path.name
        local_file["size"] = target_path.stat().st_size
    sidecar_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def central_sidecar_path(media_path: Path, suffix: str) -> Path:
    return layout_sidecar_path(media_path, suffix, DATA_ROOT, SIDECAR_DIR, library_roots())


def sidecar_candidates(media_path: Path, suffix: str) -> list[Path]:
    return layout_sidecar_candidates(media_path, suffix, DATA_ROOT, SIDECAR_DIR, library_roots())


def user_image_tags_for_file(conn, file_row: dict[str, Any]) -> dict[str, list[str]]:
    rows = conn.execute(
        f"""SELECT tag_category, tag_name
            FROM user_image_tags
            WHERE {user_file_lookup_sql()}
            ORDER BY tag_category, tag_name""",
        user_file_lookup_params(file_row),
    ).fetchall()
    tags: dict[str, list[str]] = {}
    for row in rows:
        category = normalize_user_tag_category(row["tag_category"])
        tags.setdefault(category, []).append(row["tag_name"])
    return tags


def image_view_for_file(conn, file_row: dict[str, Any]) -> dict[str, Any] | None:
    return conn.execute(
        f"""SELECT file_id, file_path, local_md5, view_count, heart_spam_count, first_viewed_at, last_viewed_at
            FROM image_views
            WHERE {user_file_lookup_sql()}
            ORDER BY last_viewed_at DESC
            LIMIT 1""",
        user_file_lookup_params(file_row),
    ).fetchone()


def earliest_timestamp(*values: str | None) -> str | None:
    timestamps = [value for value in values if value]
    return min(timestamps) if timestamps else None


def latest_timestamp(*values: str | None) -> str | None:
    timestamps = [value for value in values if value]
    return max(timestamps) if timestamps else None


def record_image_view(conn, file_row: dict[str, Any]) -> dict[str, Any]:
    existing = conn.execute(
        f"""SELECT rowid as rowid, file_id, view_count, heart_spam_count, first_viewed_at
            FROM image_views
            WHERE {user_file_lookup_sql()}
            ORDER BY last_viewed_at DESC
            LIMIT 1""",
        user_file_lookup_params(file_row),
    ).fetchone()

    if existing:
        previous_count = int(existing["view_count"] or 0)
        previous_heart_spam_count = int(existing["heart_spam_count"] or 0)
        first_viewed_at = existing["first_viewed_at"]
        if existing["file_id"] != file_row["file_id"]:
            conflict = conn.execute(
                "SELECT rowid as rowid, view_count, heart_spam_count, first_viewed_at FROM image_views WHERE file_id=?",
                (file_row["file_id"],),
            ).fetchone()
            if conflict and conflict["rowid"] != existing["rowid"]:
                previous_count += int(conflict["view_count"] or 0)
                previous_heart_spam_count += int(conflict["heart_spam_count"] or 0)
                first_viewed_at = earliest_timestamp(first_viewed_at, conflict["first_viewed_at"])
                conn.execute("DELETE FROM image_views WHERE rowid=?", (conflict["rowid"],))

        conn.execute(
            """UPDATE image_views
               SET file_id=?,
                   file_path=?,
                   local_md5=COALESCE(?, local_md5),
                   view_count=?,
                   heart_spam_count=?,
                   first_viewed_at=COALESCE(?, first_viewed_at, datetime('now')),
                   last_viewed_at=datetime('now')
               WHERE rowid=?""",
            (
                file_row["file_id"],
                file_row["path"],
                file_row.get("local_md5"),
                previous_count + 1,
                previous_heart_spam_count,
                first_viewed_at,
                existing["rowid"],
            ),
        )
    else:
        conn.execute(
            """INSERT INTO image_views
               (file_id, file_path, local_md5, view_count, heart_spam_count, first_viewed_at, last_viewed_at)
               VALUES (?, ?, ?, 1, 0, datetime('now'), datetime('now'))
               ON CONFLICT(file_id) DO UPDATE SET
                   file_path=excluded.file_path,
                   local_md5=COALESCE(excluded.local_md5, image_views.local_md5),
                   view_count=COALESCE(image_views.view_count, 0) + 1,
                   heart_spam_count=COALESCE(image_views.heart_spam_count, 0),
                   first_viewed_at=COALESCE(image_views.first_viewed_at, datetime('now')),
                   last_viewed_at=datetime('now')""",
            (file_row["file_id"], file_row["path"], file_row.get("local_md5")),
        )
    conn.commit()
    return image_view_for_file(conn, file_row) or {
        "view_count": 0,
        "heart_spam_count": 0,
        "first_viewed_at": None,
        "last_viewed_at": None,
    }


def record_heart_spam(conn, file_row: dict[str, Any]) -> dict[str, Any]:
    existing = conn.execute(
        f"""SELECT rowid as rowid, file_id, view_count, heart_spam_count, first_viewed_at, last_viewed_at
            FROM image_views
            WHERE {user_file_lookup_sql()}
            ORDER BY last_viewed_at DESC
            LIMIT 1""",
        user_file_lookup_params(file_row),
    ).fetchone()

    if existing:
        view_count = int(existing["view_count"] or 0)
        heart_spam_count = int(existing["heart_spam_count"] or 0)
        first_viewed_at = existing["first_viewed_at"]
        last_viewed_at = existing["last_viewed_at"]
        if existing["file_id"] != file_row["file_id"]:
            conflict = conn.execute(
                """SELECT rowid as rowid, view_count, heart_spam_count, first_viewed_at, last_viewed_at
                   FROM image_views WHERE file_id=?""",
                (file_row["file_id"],),
            ).fetchone()
            if conflict and conflict["rowid"] != existing["rowid"]:
                view_count += int(conflict["view_count"] or 0)
                heart_spam_count += int(conflict["heart_spam_count"] or 0)
                first_viewed_at = earliest_timestamp(first_viewed_at, conflict["first_viewed_at"])
                last_viewed_at = latest_timestamp(last_viewed_at, conflict["last_viewed_at"])
                conn.execute("DELETE FROM image_views WHERE rowid=?", (conflict["rowid"],))

        conn.execute(
            """UPDATE image_views
               SET file_id=?,
                   file_path=?,
                   local_md5=COALESCE(?, local_md5),
                   view_count=?,
                   heart_spam_count=?,
                   first_viewed_at=?,
                   last_viewed_at=?
               WHERE rowid=?""",
            (
                file_row["file_id"],
                file_row["path"],
                file_row.get("local_md5"),
                view_count,
                heart_spam_count + 1,
                first_viewed_at,
                last_viewed_at,
                existing["rowid"],
            ),
        )
    else:
        conn.execute(
            """INSERT INTO image_views
               (file_id, file_path, local_md5, view_count, heart_spam_count, first_viewed_at, last_viewed_at)
               VALUES (?, ?, ?, 0, 1, NULL, NULL)
               ON CONFLICT(file_id) DO UPDATE SET
                   file_path=excluded.file_path,
                   local_md5=COALESCE(excluded.local_md5, image_views.local_md5),
                   heart_spam_count=COALESCE(image_views.heart_spam_count, 0) + 1""",
            (file_row["file_id"], file_row["path"], file_row.get("local_md5")),
        )
    conn.commit()
    return image_view_for_file(conn, file_row) or {
        "view_count": 0,
        "heart_spam_count": 0,
        "first_viewed_at": None,
        "last_viewed_at": None,
    }


def get_file_identity(file_id: int) -> dict[str, Any]:
    with get_data_db() as conn:
        row = conn.execute(
            "SELECT id as file_id, path, local_md5 FROM files WHERE id=?",
            (file_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "File not found")
    return row


def get_post_file_identity(post_id: int) -> dict[str, Any]:
    with get_data_db() as conn:
        row = conn.execute(
            """SELECT p.id as id, f.id as file_id, f.path, f.local_md5
               FROM posts p
               JOIN files f ON f.id = p.file_id
               WHERE p.id=?""",
            (post_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Image not found")
    return row


def favorite_meta_by_file(file_ids: Iterable[int] | None = None) -> dict[int, dict[str, str | None]]:
    requested_ids = sorted({int(file_id) for file_id in file_ids}) if file_ids is not None else None
    if requested_ids == []:
        return {}
    file_filter = ""
    params: list[Any] = []
    if requested_ids is not None:
        file_filter = f"WHERE f.id IN ({','.join('?' for _ in requested_ids)})"
        params.extend(requested_ids)
    with get_data_db() as conn:
        conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))
        rows = conn.execute(
            f"""SELECT f.id as file_id,
                       MAX(fav.added_at) as added_at,
                       MAX(fav.pinned_at) as pinned_at
                FROM files f
                JOIN userdb.favorites fav ON {user_file_match("fav")}
                {file_filter}
                GROUP BY f.id"""
            , params
        ).fetchall()
    return {
        r["file_id"]: {
            "added_at": r["added_at"],
            "pinned_at": r["pinned_at"],
        }
        for r in rows
    }

def image_summary_from_row(
    row: dict[str, Any],
    fav_file_ids: set[int] | None = None,
    fav_meta_by_file: dict[int, dict[str, str | None]] | None = None,
) -> ImageSummary:
    data = dict(row)
    source_path = data.pop("path")
    favorite_added_at = data.pop("favorite_added_at", None)
    favorite_pinned_at = data.pop("favorite_pinned_at", None)
    data["thumbnail_token"] = data.pop("local_md5") or thumbnail_cache_token(source_path)
    fav_file_ids = fav_file_ids or set()
    fav_meta_by_file = fav_meta_by_file or {}
    fav_meta = fav_meta_by_file.get(row["file_id"])
    return ImageSummary(
        **data,
        is_favorite=row["file_id"] in fav_file_ids or fav_meta is not None,
        favorite_added_at=favorite_added_at or (fav_meta["added_at"] if fav_meta else None),
        favorite_pinned_at=favorite_pinned_at or (fav_meta["pinned_at"] if fav_meta else None),
    )


def relation_post_id(value: Any) -> int | None:
    if isinstance(value, dict):
        return int_or_none(value.get("id"))
    return int_or_none(value)


def child_ids_from_value(value: Any) -> list[int]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return unique_ints([relation_post_id(child) for child in value])


def relation_ids_from_raw_json(raw_json: str | None) -> tuple[int | None, list[int], bool]:
    if not raw_json:
        return None, [], False
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError:
        return None, [], False
    post = payload.get("post") if isinstance(payload, dict) else None
    if not isinstance(post, dict):
        post = payload if isinstance(payload, dict) else {}

    parent_id = int_or_none(post.get("parent_id")) or relation_post_id(post.get("parent"))
    child_ids = child_ids_from_value(post.get("children"))
    has_metadata = parent_id is not None or bool(child_ids) or bool(post.get("has_children"))
    return parent_id, child_ids, has_metadata


# Moved to modules/danbooru/relations.py and modules/danbooru/client.py;
# imported at the top and re-exported here.


def danbooru_child_search(parent_id: int) -> list[dict[str, Any]]:
    data = danbooru_json(
        "/posts.json",
        {
            "tags": f"parent:{parent_id}",
            "limit": 200,
            "only": "id,parent_id,has_children,children",
        },
    )
    if not isinstance(data, list):
        return []
    return [post for post in data if isinstance(post, dict)]


def update_relation_columns(
    conn,
    danbooru_post_id: int,
    parent_id: int | None,
    has_children: bool | None,
    child_ids: list[int] | None = None,
    *,
    update_parent: bool = True,
) -> None:
    if update_parent and parent_id == danbooru_post_id:
        parent_id = None
    if child_ids is not None:
        child_ids = [child_id for child_id in unique_ints(child_ids) if child_id != danbooru_post_id]

    assignments: list[str] = []
    params: list[Any] = []
    if update_parent:
        assignments.append("parent_id=?")
        params.append(parent_id)

    if has_children is not None:
        assignments.append("has_children=?")
        params.append(1 if has_children else 0)
    if child_ids is not None:
        assignments.append("child_ids_json=?")
        params.append(json.dumps(unique_ints(child_ids)) if child_ids else None)

    params.append(danbooru_post_id)
    conn.execute(
        f"UPDATE posts SET {', '.join(assignments)} WHERE danbooru_post_id=?",
        params,
    )


def refresh_relation_cache(conn, danbooru_post_id: int) -> None:
    post = normalize_danbooru_post_payload(
        danbooru_json(
            f"/posts/{danbooru_post_id}.json",
            {"only": "id,parent_id,has_children,children"},
        )
    )
    if not post:
        raise HTTPException(404, "Danbooru post not found")

    parent_id = int_or_none(post.get("parent_id")) or relation_post_id(post.get("parent"))
    if parent_id == danbooru_post_id:
        parent_id = None
    child_ids = child_ids_from_value(post.get("children"))
    if post.get("has_children") and not child_ids:
        child_ids = unique_ints([relation_post_id(child) for child in danbooru_child_search(danbooru_post_id)])
    child_ids = [child_id for child_id in child_ids if child_id != danbooru_post_id]
    has_children = bool(post.get("has_children") or child_ids)
    update_relation_columns(conn, danbooru_post_id, parent_id, has_children, child_ids)

    if child_ids:
        for child in danbooru_child_search(danbooru_post_id):
            child_id = relation_post_id(child)
            if child_id is None or child_id == danbooru_post_id:
                continue
            update_relation_columns(
                conn,
                child_id,
                danbooru_post_id,
                bool(child.get("has_children")),
                child_ids_from_value(child.get("children")),
            )

    if parent_id is not None:
        sibling_posts = danbooru_child_search(parent_id)
        sibling_ids = unique_ints([relation_post_id(sibling) for sibling in sibling_posts])
        sibling_ids = [sibling_id for sibling_id in sibling_ids if sibling_id != parent_id]
        update_relation_columns(
            conn,
            parent_id,
            None,
            bool(sibling_ids),
            sibling_ids,
            update_parent=False,
        )
        for sibling in sibling_posts:
            sibling_id = relation_post_id(sibling)
            if sibling_id is None or sibling_id == parent_id:
                continue
            update_relation_columns(
                conn,
                sibling_id,
                parent_id,
                bool(sibling.get("has_children")),
                child_ids_from_value(sibling.get("children")),
            )


def local_child_ids_for_parent(conn, parent_id: int, current_danbooru_id: int | None = None) -> list[int]:
    rows = conn.execute(
        """SELECT danbooru_post_id
           FROM posts
           WHERE parent_id=? AND danbooru_post_id IS NOT NULL""",
        (parent_id,),
    ).fetchall()
    ids = [int_or_none(row["danbooru_post_id"]) for row in rows]
    return [post_id for post_id in unique_ints(ids) if post_id != current_danbooru_id]


def relation_ids_for_post_row(row: dict[str, Any]) -> tuple[int | None, list[int], bool]:
    raw_parent_id, raw_child_ids, raw_has_metadata = relation_ids_from_raw_json(row.get("raw_json"))
    parent_id = int_or_none(row.get("parent_id")) or raw_parent_id
    child_ids = unique_ints([
        *child_ids_from_value(row.get("child_ids_json")),
        *raw_child_ids,
    ])
    has_metadata = parent_id is not None or bool(child_ids) or bool(row.get("has_children")) or raw_has_metadata
    return parent_id, child_ids, has_metadata


def build_image_relations(conn, row: dict[str, Any]) -> ImageRelations:
    current_danbooru_id = int_or_none(row.get("danbooru_post_id"))
    if current_danbooru_id is None:
        return ImageRelations()

    parent_id, child_ids, has_metadata = relation_ids_for_post_row(row)
    child_ids = unique_ints([
        *child_ids,
        *local_child_ids_for_parent(conn, current_danbooru_id, current_danbooru_id),
    ])
    child_ids = [post_id for post_id in child_ids if post_id != current_danbooru_id]

    sibling_ids: list[int] = []
    if parent_id is not None:
        sibling_ids.extend(local_child_ids_for_parent(conn, parent_id, current_danbooru_id))
        parent_row = conn.execute(
            "SELECT parent_id, has_children, child_ids_json, raw_json FROM posts WHERE danbooru_post_id=?",
            (parent_id,),
        ).fetchone()
        if parent_row:
            _, parent_child_ids, parent_has_metadata = relation_ids_for_post_row(parent_row)
            sibling_ids.extend(parent_child_ids)
            has_metadata = has_metadata or parent_has_metadata
    sibling_ids = [post_id for post_id in unique_ints(sibling_ids) if post_id != current_danbooru_id]

    all_relation_ids = unique_ints([
        parent_id,
        *child_ids,
        *sibling_ids,
    ])
    local_infos = related_infos_for_danbooru_ids(conn, all_relation_ids)

    return ImageRelations(
        parent=related_info_for_id(parent_id, local_infos) if parent_id is not None else None,
        siblings=[related_info_for_id(post_id, local_infos) for post_id in sibling_ids],
        children=[related_info_for_id(post_id, local_infos) for post_id in child_ids],
        has_metadata=has_metadata,
    )


SIDECAR_LAYOUT_MIGRATION_KEY = "sidecar_layout_v2_complete"


def run_user_recovery_checkpoint() -> None:
    """Checkpoint the shared, irreplaceable user DB. Suite-level; always safe."""
    try:
        checkpoint = create_local_recovery_checkpoint("startup")
        logger.info("Local recovery checkpoint: %s", checkpoint["message"])
    except Exception as exc:  # noqa: BLE001 - recovery must not prevent startup.
        logger.warning("Local recovery checkpoint failed: %s", exc)


def run_sidecar_layout_migration() -> None:
    """Danbooru-only: fold legacy sidecars into the canonical layout, once."""
    try:
        with get_data_db() as migration_connection:
            completed = migration_connection.execute(
                "SELECT value FROM metadata WHERE key=?",
                (SIDECAR_LAYOUT_MIGRATION_KEY,),
            ).fetchone()
            if completed:
                return
            media_paths = [Path(row["path"]) for row in migration_connection.execute("SELECT path FROM files")]

        migration_result = migrate_existing_sidecars(
            media_paths,
            DATA_ROOT,
            SIDECAR_DIR,
            library_roots(),
        )
        if migration_result["copied"] or migration_result["failed"]:
            logger.info("Sidecar layout migration: %s", migration_result)

        if not migration_result["failed"]:
            with get_data_db() as migration_connection:
                migration_connection.execute(
                    "INSERT INTO metadata(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (SIDECAR_LAYOUT_MIGRATION_KEY, datetime.now(timezone.utc).isoformat()),
                )
                migration_connection.commit()
    except Exception as exc:  # noqa: BLE001 - maintenance must not break the running app.
        logger.warning("Sidecar layout migration failed: %s", exc)


def run_startup_maintenance() -> None:
    """Compatibility wrapper: suite recovery checkpoint + Danbooru sidecar migration."""
    run_user_recovery_checkpoint()
    run_sidecar_layout_migration()


def reconcile_module_folders() -> None:
    """Let every registered module publish its folders into the shared list.

    A module keeps its own storage as the source of truth and mirrors the
    folders it owns into the base browse-list under its own role, pruning stale
    rows for that role. Self-healing: catches any register/remove hook that
    didn't fire. Module -> base only, never the reverse.

    The base has no publish hook, so iterating the whole registry is a no-op for
    it and no module is named here.
    """
    try:
        with get_user_db() as connection:
            for descriptor in MODULE_REGISTRY:
                descriptor.publish(connection)
    except Exception as exc:  # noqa: BLE001 - never block startup.
        logger.warning("Could not reconcile module folders into the Files base: %s", exc)


def danbooru_module_enabled() -> bool:
    """Whether the Danbooru module is enabled in the shared user DB.

    Returns False when the module is not registered at all, so a suite built
    without it never starts Danbooru's background work.

    Fail-safe: if the enabled set cannot be read, assume enabled so an existing
    library is never hidden by a transient error.
    """
    descriptor = MODULE_REGISTRY.get(DANBOORU_SLUG)
    if descriptor is None:
        return False
    try:
        with get_user_db() as connection:
            suite_modules.ensure_schema(connection)
            return descriptor.slug in suite_modules.enabled_ids(connection)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read enabled modules; assuming Danbooru enabled: %s", exc)
        return True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Suite-level startup — always runs, independent of any module.
    promotion = promote_user_database()
    if promotion.get("promoted"):
        logger.info("Promoted user database to suite root: %s", promotion["destination"])
    backup_promotion = promote_legacy_module_backups()
    if backup_promotion.get("promoted"):
        logger.info(
            "Copied and verified %s legacy module backups into the suite backup directory; source preserved",
            backup_promotion["files"],
        )
    migration = migrate_legacy_default_metadata()
    if migration["migrated"]:
        logger.info(
            "Flattened legacy metadata directory: %s moved, %s identical duplicates removed",
            migration["moved"],
            migration["deduplicated"],
        )
    init_data_db()
    init_user_db()

    # Protect the irreplaceable user DB regardless of which modules are enabled.
    checkpoint_task = asyncio.create_task(
        asyncio.to_thread(run_user_recovery_checkpoint),
        name="suite-recovery-checkpoint",
    )
    background_tasks = [checkpoint_task]

    # Danbooru's background work (sidecar file-walk + the auto-ingest watcher)
    # runs only when the module is enabled — the app boots without it otherwise.
    if danbooru_module_enabled():
        reconcile_module_folders()
        sidecar_task = asyncio.create_task(
            asyncio.to_thread(run_sidecar_layout_migration),
            name="danbooru-sidecar-migration",
        )
        automation_task = asyncio.create_task(automation_loop(), name="danbooru-auto-ingest")
        background_tasks += [sidecar_task, automation_task]
    else:
        logger.info("Danbooru module not enabled; skipping its background startup")

    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title=DISPLAY_NAME, version=VERSION, lifespan=lifespan)


@app.middleware("http")
async def restrict_local_browser_access(request: Request, call_next):
    rejection = validate_local_browser_request(
        host_header=request.headers.get("host", ""),
        scheme=request.url.scheme,
        origin_header=request.headers.get("origin"),
        fetch_site_header=request.headers.get("sec-fetch-site"),
        lan_host=os.environ.get("KEIVOTOS_LAN_HOST"),
    )
    if rejection is not None:
        status_code, detail = rejection
        return JSONResponse(status_code=status_code, content={"detail": detail})
    return await call_next(request)


@app.middleware("http")
async def add_server_timing_header(request: Request, call_next):
    started_at = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started_at) * 1000
    response.headers["Server-Timing"] = f'app;dur={duration_ms:.2f};desc="{DISPLAY_NAME}"'
    return response


# ---------------------------------------------------------------------------
# Search / filter helpers (adapted from danbooru_gallery_dl.py)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Image endpoints
# ---------------------------------------------------------------------------























# ---------------------------------------------------------------------------
# File serving
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Popularity
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

from services.home import *  # compatibility facade for Home discovery services



# ---------------------------------------------------------------------------
# Daily challenges
# ---------------------------------------------------------------------------

from services.challenges import *  # compatibility facade for daily challenge services



# ---------------------------------------------------------------------------
# Tag wiki cache
# ---------------------------------------------------------------------------
# Moved to modules/danbooru/tag_wiki.py; imported at the top.

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
# Moved to modules/danbooru/tags.py; imported at the top.

# ---------------------------------------------------------------------------
# Artist profile media archive (Twitter/X and Pixiv avatars/banners)
# ---------------------------------------------------------------------------
# Moved to modules/danbooru/artist_profiles.py; imported at the top.

# ---------------------------------------------------------------------------
# Artist follows (local watchlist with Danbooru post ID placeholders)
# ---------------------------------------------------------------------------
# Moved to modules/danbooru/artist_follows.py; imported at the top.

# ---------------------------------------------------------------------------
# Folders
# ---------------------------------------------------------------------------











# ---------------------------------------------------------------------------
# Favorites
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# Favorite Tags (standalone tag bookmarks)
# ---------------------------------------------------------------------------










# Moved to services/user_library.py; imported at the top and re-exported here.








# ---------------------------------------------------------------------------
# Blacklist Tags
# ---------------------------------------------------------------------------


# Moved to services/user_library.py; imported at the top and re-exported here.










# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

# Moved to services/collections.py; imported at the top and re-exported here.
















# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

# Moved to services/profile.py; imported at the top and re-exported here.




# ---------------------------------------------------------------------------
# Tools (run danbooru_gallery_dl.py commands)
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "danbooru_gallery_dl.py"
PROJECT_ROOT = DATA_ROOT
TOOL_WORKING_DIRECTORY = SCRIPT_PATH.parent.parent

_running_tasks: dict[str, dict[str, Any]] = {}
_running_processes: dict[str, subprocess.Popen[str]] = {}
_tool_state_lock = threading.RLock()
_tool_operation_lock = threading.RLock()
_active_tool_id: str | None = None


def active_tool_id() -> str | None:
    """Return the live tool owner while holding the shared state lock."""
    with _tool_state_lock:
        return _active_tool_id


def tool_task_snapshot(tool_id: str) -> dict[str, Any] | None:
    """Return request-safe task state while the worker may still be updating it."""
    with _tool_state_lock:
        task = _running_tasks.get(tool_id)
        return copy.deepcopy(task) if task is not None else None


@contextmanager
def exclusive_tool_operation(operation_name: str):
    """Prevent a restore/backup window from racing a newly launched tool."""
    with _tool_operation_lock:
        with _tool_state_lock:
            if _active_tool_id:
                raise RuntimeError(f"Wait for {_active_tool_id} to finish before {operation_name}")
        yield


def _tool_base_command() -> list[str]:
    launcher = (
        [sys.executable, "--pipeline"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-Bu", str(SCRIPT_PATH)]
    )
    return [
        *launcher,
        "--root", str(PROJECT_ROOT),
        "--gallery-dl-dir", str(GALLERY_DL_DIR),
        "--sidecar-dir", str(SIDECAR_DIR),
        "--user-db", str(USER_DB_PATH),
    ]


def _sync_scan_paths() -> list[str]:
    """Every folder a full sync should cover: scan folders plus registered folders."""
    paths: list[str] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        if not path.is_dir():
            return
        key = os.path.normcase(str(path))
        if key in seen:
            return
        seen.add(key)
        paths.append(str(path))

    for name in SCAN_FOLDERS:
        add(DATA_ROOT / name)
    if not paths:
        add(DATA_ROOT)
    for row in registered_folder_rows():
        if row["path"]:
            add(Path(row["path"]))
        else:
            add(DATA_ROOT / row["name"])
    return paths


def _extra_root_args() -> list[str]:
    """--extra-root flags for registered folders living outside the data root."""
    args: list[str] = []
    resolved_root = DATA_ROOT.resolve(strict=False)
    for row in registered_folder_rows():
        if not row["path"]:
            continue
        resolved = Path(row["path"]).resolve(strict=False)
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            args.extend(["--extra-root", str(resolved)])
    return args


def _sync_command(paths: list[str]) -> list[str]:
    return [
        *_tool_base_command(),
        "sync", "--output", str(DATA_DB_PATH), "--no-raw-json",
        *paths,
    ]


def _import_discover_command(paths: list[str]) -> list[str]:
    return [
        *_tool_base_command(),
        "import-discover", "--output", str(DATA_DB_PATH),
        *paths,
    ]


def _import_enrich_command(paths: list[str]) -> list[str]:
    return [
        *_tool_base_command(),
        "import-enrich", "--output", str(DATA_DB_PATH), "--workers", "3",
        *paths,
    ]


def _import_finalize_command(paths: list[str]) -> list[str]:
    return [
        *_tool_base_command(),
        "import-finalize", "--output", str(DATA_DB_PATH), "--no-raw-json",
        *paths,
    ]


def _start_sync_run(paths: list[str]) -> dict[str, Any]:
    return _launch_tool("sync", [_sync_command(paths)])


def _start_folder_import(paths: list[str]) -> dict[str, Any]:
    return _start_sync_run(paths)










def _launch_tool(
    tool_id: str,
    tool_commands: list[list[str]],
    *,
    environment: dict[str, str] | None = None,
    stage_names: list[str] | None = None,
    on_success: Callable[[], str | None] | None = None,
) -> dict[str, Any]:
    global _active_tool_id
    with _tool_operation_lock:
        with _tool_state_lock:
            if _active_tool_id:
                status = "already_running" if _active_tool_id == tool_id else "busy"
                return {"status": status, "active_tool_id": _active_tool_id}
            _active_tool_id = tool_id
            _running_tasks[tool_id] = {
                "status": "running",
                "output": "",
                "progress": 0,
                "total": 0,
                "stage": (stage_names or [None])[0],
                "stage_index": 1,
                "stage_total": len(tool_commands),
                "cancellable": True,
                "current_file": None,
                "current_file_path": None,
                "current_file_status": None,
                "file_results": [],
                "result_counts": {"matched": 0, "no_match": 0, "error": 0},
            }

    def _run():
        global _active_tool_id
        try:
            # Keep only the console tail exposed to Settings. A 40k-file import
            # must not retain every subprocess line for the lifetime of the job.
            lines: deque[str] = deque(maxlen=100)
            for step_index, cmd in enumerate(tool_commands, 1):
                with _tool_state_lock:
                    task = _running_tasks[tool_id]
                    if task["status"] == "cancelling":
                        task["status"] = "cancelled"
                        return
                    stage = (
                        stage_names[step_index - 1]
                        if stage_names and step_index <= len(stage_names)
                        else f"Step {step_index} of {len(tool_commands)}"
                    )
                    task["stage_index"] = step_index
                    task["stage"] = stage
                    if len(tool_commands) > 1:
                        lines.append(f"{stage}\n")
                        task.update(
                            {
                                "output": "".join(lines),
                                "progress": 0,
                                "total": 0,
                                "current_file": None,
                                "current_file_path": None,
                                "current_file_status": None,
                            }
                        )
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(TOOL_WORKING_DIRECTORY),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=environment or credential_environment(),
                )
                with _tool_state_lock:
                    _running_processes[tool_id] = proc
                assert proc.stdout is not None
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if line.startswith("STAGE:"):
                        with _tool_state_lock:
                            _running_tasks[tool_id]["stage"] = line.strip().split(":", 1)[1].replace("_", " ").title()
                        continue
                    if line.startswith("PROGRESS:"):
                        parts = line.strip().split(":", 1)[1].split("/")
                        if len(parts) == 2:
                            try:
                                progress = int(parts[0])
                                total = int(parts[1])
                            except ValueError:
                                pass
                            else:
                                with _tool_state_lock:
                                    _running_tasks[tool_id].update({"progress": progress, "total": total})
                        continue
                    if line.startswith("FILE_STATUS:"):
                        try:
                            event = json.loads(line.split(":", 1)[1])
                        except (json.JSONDecodeError, TypeError):
                            continue
                        filename = str(event.get("filename") or Path(str(event.get("path") or "")).name)
                        status = str(event.get("status") or "working")
                        with _tool_state_lock:
                            task = _running_tasks[tool_id]
                            task["current_file"] = filename or None
                            task["current_file_path"] = str(event.get("path") or "") or None
                            task["current_file_status"] = status
                            if status in {"matched", "no_match", "error"}:
                                result = {
                                    "filename": filename,
                                    "path": str(event.get("path") or ""),
                                    "status": status,
                                    "detail": str(event.get("detail") or ""),
                                    "index": event.get("index"),
                                    "total": event.get("total"),
                                }
                                results = task.setdefault("file_results", [])
                                results.append(result)
                                if len(results) > 250:
                                    del results[:-250]
                                counts = task.setdefault("result_counts", {})
                                counts[status] = int(counts.get(status, 0)) + 1
                        continue
                    lines.append(line)
                    with _tool_state_lock:
                        _running_tasks[tool_id]["output"] = "".join(lines)
                proc.stdout.close()
                proc.wait()
                with _tool_state_lock:
                    _running_processes.pop(tool_id, None)
                    task = _running_tasks[tool_id]
                    if task["status"] == "cancelling":
                        task.update({"status": "cancelled", "cancellable": False})
                        return
                    if proc.returncode != 0:
                        task.update({"status": "error", "output": "".join(lines), "cancellable": False})
                        return
            if on_success is not None:
                post_step_output = on_success()
                if post_step_output:
                    lines.append(post_step_output.rstrip() + "\n")
            if any("sync" in command for command in tool_commands):
                try:
                    checkpoint = create_local_recovery_checkpoint("sync")
                    lines.append(checkpoint["message"].rstrip() + "\n")
                except Exception as exc:  # noqa: BLE001 - sync itself succeeded.
                    lines.append(f"Local recovery checkpoint failed: {exc}\n")
            clear_home_caches()
            with _tool_state_lock:
                _running_tasks[tool_id].update(
                    {"status": "done", "output": "".join(lines), "cancellable": False}
                )
        except Exception as exc:
            with _tool_state_lock:
                task = _running_tasks.setdefault(tool_id, {})
                task.update({"status": "error", "output": str(exc), "cancellable": False})
        finally:
            with _tool_state_lock:
                _running_processes.pop(tool_id, None)
                if _active_tool_id == tool_id:
                    _active_tool_id = None

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}


def _cancel_tool(tool_id: str) -> dict[str, Any]:
    with _tool_state_lock:
        task = _running_tasks.get(tool_id)
        if not task or task.get("status") not in {"running", "cancelling"}:
            return {"status": task.get("status", "idle") if task else "idle"}
        task["status"] = "cancelling"
        task["cancellable"] = False
        process = _running_processes.get(tool_id)
    if process and process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            process.terminate()
    return {"status": "cancelling"}

__all__ = [name for name in globals() if not name.startswith("__")]
