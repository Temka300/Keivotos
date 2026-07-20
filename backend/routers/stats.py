from __future__ import annotations

from fastapi import APIRouter, HTTPException
from core import *  # shared query, database, and media helpers
from database import get_user_db
from models import UserSetting, UserSettingUpdate
from product import SUITE_NAME

router = APIRouter()
PROFILE_NAME_KEY = "profile_name"
SUPPORTED_USER_SETTING_KEYS = {PROFILE_NAME_KEY}


def _user_setting_value(key: str, value: str) -> str:
    if key != PROFILE_NAME_KEY:
        raise HTTPException(404, "User setting not found")
    normalized = value.strip()[:40]
    return normalized or SUITE_NAME


@router.get("/api/user-settings/{key}", response_model=UserSetting)
def get_user_setting(key: str):
    if key not in SUPPORTED_USER_SETTING_KEYS:
        raise HTTPException(404, "User setting not found")
    with get_user_db() as conn:
        row = conn.execute("SELECT value FROM user_settings WHERE key=?", (key,)).fetchone()
    value = _user_setting_value(key, row["value"] if row else SUITE_NAME)
    return UserSetting(key=key, value=value)


@router.put("/api/user-settings/{key}", response_model=UserSetting)
def put_user_setting(key: str, update: UserSettingUpdate):
    value = _user_setting_value(key, update.value)
    with get_user_db() as conn:
        conn.execute(
            """INSERT INTO user_settings(key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value,
                   updated_at=excluded.updated_at""",
            (key, value),
        )
        conn.commit()
    return UserSetting(key=key, value=value)


@router.get("/api/stats", response_model=Stats)
def stats():
    with get_data_db() as conn:
        library = conn.execute(
            """SELECT COUNT(*) as total_images,
                      COALESCE(SUM(COALESCE(f.size, 0)), 0) as total_storage_bytes,
                      MIN(NULLIF(f.downloaded_at, '')) as downloaded_from,
                      MAX(NULLIF(f.downloaded_at, '')) as downloaded_to,
                      AVG(p.score) as average_score,
                      MAX(p.score) as best_score
               FROM files f
               LEFT JOIN posts p ON p.file_id = f.id"""
        ).fetchone()
        tag_count = conn.execute("SELECT COUNT(*) as cnt FROM tags").fetchone()["cnt"]
        folder_count = conn.execute("SELECT COUNT(DISTINCT folder) as cnt FROM files").fetchone()["cnt"]

        conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))
        try:
            fav_count = conn.execute(
                f"""SELECT COUNT(DISTINCT f.id) as cnt
                    FROM files f
                    JOIN userdb.favorites fav ON {user_file_match("fav")}"""
            ).fetchone()["cnt"]
            collection_item_count = conn.execute(
                f"""SELECT COUNT(DISTINCT f.id) as cnt
                    FROM files f
                    JOIN userdb.collection_items ci ON {user_file_match("ci")}"""
            ).fetchone()["cnt"]
            seen_images = conn.execute(
                f"""SELECT COUNT(DISTINCT f.id) as cnt
                    FROM files f
                    JOIN userdb.image_views iv ON {user_file_match("iv")}
                    WHERE COALESCE(iv.view_count, 0) > 0"""
            ).fetchone()["cnt"]
            total_image_views = conn.execute(
                "SELECT COALESCE(SUM(view_count), 0) as cnt FROM userdb.image_views"
            ).fetchone()["cnt"]
            view_dates = conn.execute(
                """SELECT MIN(first_viewed_at) as first_viewed_at,
                          MAX(last_viewed_at) as last_viewed_at
                   FROM userdb.image_views
                   WHERE COALESCE(view_count, 0) > 0"""
            ).fetchone()
            total_collections = conn.execute(
                "SELECT COUNT(*) as cnt FROM userdb.collections"
            ).fetchone()["cnt"]
            total_user_tags = conn.execute(
                "SELECT COUNT(*) as cnt FROM userdb.user_image_tags"
            ).fetchone()["cnt"]
            total_favorite_tags = conn.execute(
                "SELECT COUNT(*) as cnt FROM userdb.favorite_tags"
            ).fetchone()["cnt"]
            total_followed_artists = conn.execute(
                "SELECT COUNT(*) as cnt FROM userdb.artist_follows"
            ).fetchone()["cnt"]
            avatar = profile_asset(
                conn,
                ["c-Logo", "c-Logo_Used-Most", "Danbooru_Logo"],
                "p.width IS NOT NULL AND p.height IS NOT NULL AND p.height > 0 AND p.width BETWEEN p.height * 0.65 AND p.height * 1.55",
            )
            banner = profile_asset(
                conn,
                ["c-Logo-Banner", "Danbooru_Logo_Banner", "Wallpaper"],
                "p.width IS NOT NULL AND p.height IS NOT NULL AND p.height > 0 AND p.width >= p.height * 1.8",
            )
        finally:
            conn.execute("DETACH DATABASE userdb")

    return Stats(
        total_images=library["total_images"],
        total_tags=tag_count,
        total_folders=folder_count,
        total_favorites=fav_count,
        total_collections=total_collections,
        total_image_views=int(total_image_views or 0),
        seen_images=seen_images,
        total_storage_bytes=int(library["total_storage_bytes"] or 0),
        total_user_tags=total_user_tags,
        total_favorite_tags=total_favorite_tags,
        total_followed_artists=total_followed_artists,
        total_collection_items=collection_item_count,
        average_score=library["average_score"],
        best_score=library["best_score"],
        downloaded_from=library["downloaded_from"],
        downloaded_to=library["downloaded_to"],
        first_viewed_at=view_dates["first_viewed_at"] if view_dates else None,
        last_viewed_at=view_dates["last_viewed_at"] if view_dates else None,
        profile_avatar_file_id=avatar["file_id"] if avatar else None,
        profile_avatar_token=profile_asset_token(avatar),
        profile_banner_file_id=banner["file_id"] if banner else None,
        profile_banner_token=profile_asset_token(banner),
    )
