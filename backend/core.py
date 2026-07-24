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
from modules.danbooru.search import (
    BARE_FILENAME_RE,
    DATE_FILTER_PREFIXES,
    DIMENSION_FILTER_PREFIXES,
    DIMENSION_TOKEN_RE,
    FILENAME_FILTER_PREFIXES,
    HEART_SPAM_FILTER_PREFIXES,
    NUMERIC_FILTERS,
    POST_ID_FILTER_PREFIXES,
    SHAPE_FILTER_PREFIXES,
    SHAPE_PRESET_ALIASES,
    USER_TAG_CATEGORY,
    _add_date_filter,
    _add_numeric,
    _date_filter_value,
    _filename_like_value,
    add_dimension_filter,
    add_filename_filter,
    add_post_id_filter,
    add_shape_filter,
    add_where_clause,
    build_where,
    combined_image_search,
    normalize_dimension_tokens,
    normalize_search_phrases,
    normalize_shape_term,
    parse_search_terms,
    search_has_post_id_filter,
    search_requires_user_db,
    shape_filter_clause,
)
from modules.danbooru.folder_registry import registered_folder_rows
from modules.danbooru.duplicate_review import (
    COPY_SUFFIX_RE,
    duplicate_filename_key,
    duplicate_filter_sql,
    duplicate_group_expr,
)
from modules.danbooru.media_files import (
    STREAM_CHUNK_SIZE,
    file_range_iter,
    media_placeholder,
    parse_range_header,
)
from modules.danbooru.paths import (
    central_sidecar_path,
    ensure_managed_path,
    folder_target,
    move_payload_text,
    registered_folder_path,
    rewrite_json_sidecar,
    sidecar_candidates,
)
from modules.danbooru.folder_registry import library_roots
from lifecycle import (
    SIDECAR_LAYOUT_MIGRATION_KEY,
    danbooru_module_enabled,
    lifespan,
    reconcile_module_folders,
    run_sidecar_layout_migration,
    run_startup_maintenance,
    run_user_recovery_checkpoint,
)
from app_factory import add_server_timing_header, app, restrict_local_browser_access
from modules.danbooru.tools import (
    PROJECT_ROOT,
    SCRIPT_PATH,
    TOOL_WORKING_DIRECTORY,
    _active_tool_id,
    _cancel_tool,
    _extra_root_args,
    _import_discover_command,
    _import_enrich_command,
    _import_finalize_command,
    _launch_tool,
    _running_processes,
    _running_tasks,
    _start_folder_import,
    _start_sync_run,
    _sync_command,
    _sync_scan_paths,
    _tool_base_command,
    _tool_operation_lock,
    _tool_state_lock,
    active_tool_id,
    exclusive_tool_operation,
    tool_task_snapshot,
)
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
    build_image_relations,
    child_ids_from_value,
    danbooru_child_search,
    local_child_ids_for_parent,
    refresh_relation_cache,
    relation_ids_for_post_row,
    relation_ids_from_raw_json,
    relation_post_id,
    update_relation_columns,
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














# registered_folder_rows moved to modules/danbooru/folder_registry.py.

# library_roots moved to modules/danbooru/folder_registry.py.















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


# Relation parsing and refresh moved to modules/danbooru/relations.py;
# imported at the top and re-exported here.

# Lifecycle moved to lifecycle.py; the FastAPI app to app_factory.py.
# Both are imported at the top and re-exported here.
# ---------------------------------------------------------------------------
# Search / filter helpers (adapted from danbooru_gallery_dl.py)
# ---------------------------------------------------------------------------
# Moved to modules/danbooru/search.py; imported at the top.

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
# Moved to modules/danbooru/tools.py; imported at the top.


# Every name this facade holds — including the private helpers extracted modules
# re-export — stays available to routers that still use `from core import *`.
__all__ = [name for name in globals() if not name.startswith("__")]

