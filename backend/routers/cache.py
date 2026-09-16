from __future__ import annotations

from fastapi import APIRouter
from config import save_config
from database import get_data_db
from models import ThumbnailCacheLimitUpdate
from thumbnails import cleanup_thumbnail_cache, clear_thumbnail_cache, prune_thumbnail_cache, thumbnail_cache_status, thumbnail_cache_token

router = APIRouter()


def _valid_thumbnail_keys() -> set[str]:
    with get_data_db() as connection:
        rows = connection.execute("SELECT path, local_md5 FROM files").fetchall()
    return {
        (str(row["local_md5"]).lower() if row["local_md5"] and len(str(row["local_md5"])) == 32 else thumbnail_cache_token(row["path"]))
        for row in rows
    }


@router.get("/api/thumbnails/cache")
def get_thumbnail_cache():
    return thumbnail_cache_status()


@router.post("/api/thumbnails/cache/cleanup")
def cleanup_thumbnails():
    return cleanup_thumbnail_cache(_valid_thumbnail_keys())


@router.post("/api/thumbnails/cache/clear")
def clear_thumbnails():
    removed = clear_thumbnail_cache()
    return {**thumbnail_cache_status(), "removed": removed}


@router.put("/api/thumbnails/cache/limit")
def update_thumbnail_limit(update: ThumbnailCacheLimitUpdate):
    save_config({"thumbnail_cache_limit_gb": update.limit_gb})
    return prune_thumbnail_cache(update.limit_gb * 1024 * 1024 * 1024)
