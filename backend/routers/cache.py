from __future__ import annotations

from fastapi import APIRouter
from config import save_config
from models import ThumbnailCacheLimitUpdate
from thumbnails import cleanup_thumbnail_cache, clear_thumbnail_cache, prune_thumbnail_cache, thumbnail_cache_status, thumbnail_cache_token

router = APIRouter()


def _valid_thumbnail_keys() -> None:
    # Files covers and attachments can create content-keyed thumbnails without a
    # corresponding Danbooru row. Retain current versions across all owners.
    # Only obsolete format/size variants are provably stale without rehashing media.
    return None


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
