"""Discovery and bounded playback diagnostics; bytes use guarded shared Files routes."""
import logging
from pathlib import PurePosixPath
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from config import FILES_DB_PATH
from database import get_user_db
from files_base import index, sources

router = APIRouter()
logger = logging.getLogger("keivotos.video")
VIDEO_EXTENSIONS = ("mp4", "m4v", "webm", "mkv", "mov", "avi", "ogv")


def video_sources():
    with get_user_db() as connection:
        sources.ensure_sources_schema(connection)
        return [source.source_id for source in sources.list_sources(connection)
                if source.role == "video" and source.visible]


@router.get("/api/video/library")
def library(q: str = Query("", max_length=256), offset: int = Query(0, ge=0),
            limit: int = Query(120, ge=1, le=240)):
    owners = video_sources()
    if not owners:
        return {"items": [], "total": 0}
    placeholders = ','.join('?' for _ in owners)
    extensions = ','.join('?' for _ in VIDEO_EXTENSIONS)
    where = (f"source_id IN ({placeholders}) AND ext IN ({extensions}) "
             "AND is_dir=0 AND available=1 AND instr(lower(name), lower(?))>0")
    params = [*owners, *VIDEO_EXTENSIONS, q.strip()]
    with index.open_index(FILES_DB_PATH) as connection:
        total = connection.execute(f"SELECT count(*) FROM files_index WHERE {where}", params).fetchone()[0]
        rows = connection.execute(
            f"SELECT source_id,relative_path AS path,name,ext,size,mtime FROM files_index WHERE {where} "
            "ORDER BY name COLLATE NOCASE, path LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
    return {"items": [dict(row) for row in rows], "total": total}


class PlaybackFailure(BaseModel):
    source_id: str = Field(max_length=256)
    path: str = Field(max_length=4096)
    reason: Literal["unsupported_format", "network", "decode", "unsupported_codec", "playback", "fullscreen"]


@router.post("/api/video/playback-error")
def playback_error(failure: PlaybackFailure):
    if failure.source_id not in video_sources():
        raise HTTPException(404, "Video folder is unavailable")
    # Match a known indexed item; no caller-supplied diagnostic text or file reads.
    with index.open_index(FILES_DB_PATH) as connection:
        row = connection.execute(
            "SELECT name FROM files_index WHERE source_id=? AND relative_path=? AND is_dir=0",
            (failure.source_id, failure.path)).fetchone()
    if row is None or PurePosixPath(failure.path).suffix.lower().lstrip('.') not in VIDEO_EXTENSIONS:
        raise HTTPException(404, "Video is unavailable")
    logger.warning("Playback failed: source=%r file=%r reason=%s", failure.source_id, failure.path, failure.reason)
    return {"status": "logged"}
