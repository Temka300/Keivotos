"""HTTP surface for the Files base: ``/api/files/*`` (V1.1.0).

The Files base is always-on and neutral. This router is the transport layer over
the isolated ``files_base`` engine: it registers/lists/removes sources, triggers
scans, and answers browse/search queries. It authors no metadata and never
moves or deletes files on disk (removing a source only un-indexes).

Isolation: this router does NOT ``from core import *``. It imports only the
config values it needs, the shared user-DB accessor, and the standalone
``files_base`` engine. See docs/important/SUITE_MODULE_CONTRACT.md.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import config
from database import get_user_db
from files_base import filesystem, hashing, index, sources

router = APIRouter()


# --- API contract models (base namespace) ---

class FileNode(BaseModel):
    source_id: str
    relative_path: str
    parent: str
    name: str
    ext: str | None
    is_dir: bool
    size: int | None
    mtime: int | None
    available: bool


class SourceInfo(BaseModel):
    source_id: str
    path: str
    display_name: str
    role: str
    visible: bool
    added_at: str | None = None


class SourceRegister(BaseModel):
    path: str
    display_name: str | None = None


class ScanSummary(BaseModel):
    added: int
    updated: int
    files: int
    directories: int
    unavailable: int


class RemovalResult(BaseModel):
    removed: bool
    unindexed: int


class HashProgress(BaseModel):
    hashed: int
    failed: int
    remaining: int


class DuplicateGroup(BaseModel):
    content_hash: str
    files: list[FileNode]


class FsEntry(BaseModel):
    name: str
    path: str


class FsListing(BaseModel):
    path: str
    parent: str | None
    is_root: bool
    entries: list[FsEntry]


class PickResult(BaseModel):
    path: str | None
    native: bool


@router.post("/api/files/pick", response_model=PickResult)
def pick_folder() -> PickResult:
    """Open the native Windows folder dialog (same one Danbooru uses).

    On non-Windows, reports ``native=false`` so the UI can fall back to the
    in-app folder picker.
    """
    if os.name != "nt":
        return PickResult(path=None, native=False)
    try:
        path = filesystem.native_pick_folder(config.CODE_ROOT)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"Folder picker failed: {exc}")
    return PickResult(path=path, native=True)


def _forbidden_source_paths() -> list[Path]:
    """Keivotos's own data tree — never registerable as a browsable source."""
    return [config.SUITE_HOME]


def _entry_to_node(entry: index.FileEntry) -> FileNode:
    return FileNode(
        source_id=entry.source_id,
        relative_path=entry.relative_path,
        parent=entry.parent,
        name=entry.name,
        ext=entry.ext,
        is_dir=entry.is_dir,
        size=entry.size,
        mtime=entry.mtime,
        available=entry.available,
    )


def _source_to_info(source: sources.Source) -> SourceInfo:
    return SourceInfo(
        source_id=source.source_id,
        path=source.path,
        display_name=source.display_name,
        role=source.role,
        visible=source.visible,
        added_at=source.added_at,
    )


def _scan_registered_source(
    index_conn,
    source: sources.Source,
    all_sources: list[sources.Source],
) -> dict[str, int]:
    excluded = [
        Path(candidate.path)
        for candidate in sources.descendant_sources(source, all_sources)
    ]
    return index.scan_source(
        index_conn,
        source.source_id,
        Path(source.path),
        excluded_roots=excluded,
    )


@router.get("/api/files/fs", response_model=FsListing)
def browse_filesystem(path: str = Query("")) -> FsListing:
    """List sub-directories so the UI can pick a folder to register."""
    return FsListing(**filesystem.list_directories(path))


@router.get("/api/files/sources", response_model=list[SourceInfo])
def list_sources() -> list[SourceInfo]:
    with get_user_db() as user_conn:
        sources.ensure_sources_schema(user_conn)
        return [_source_to_info(source) for source in sources.list_sources(user_conn)]


@router.post("/api/files/sources", response_model=SourceInfo)
def register_source(payload: SourceRegister) -> SourceInfo:
    reason = sources.unsafe_source_reason(payload.path, _forbidden_source_paths())
    if reason is not None:
        raise HTTPException(status_code=400, detail=reason)
    with get_user_db() as user_conn:
        sources.ensure_sources_schema(user_conn)
        source = sources.register_source(user_conn, payload.path, payload.display_name)
        all_sources = sources.list_sources(user_conn)
    # Initial cheap scan so the folder is browsable immediately.
    with index.open_index(config.FILES_DB_PATH) as index_conn:
        _scan_registered_source(index_conn, source, all_sources)
    return _source_to_info(source)


@router.post("/api/files/sources/{source_id}/scan", response_model=ScanSummary)
def scan_source(source_id: str) -> ScanSummary:
    with get_user_db() as user_conn:
        sources.ensure_sources_schema(user_conn)
        source = sources.get_source(user_conn, source_id)
        all_sources = sources.list_sources(user_conn)
    if source is None:
        raise HTTPException(status_code=404, detail="Unknown source")
    with index.open_index(config.FILES_DB_PATH) as index_conn:
        summary = _scan_registered_source(index_conn, source, all_sources)
    return ScanSummary(**summary)


@router.delete("/api/files/sources/{source_id}", response_model=RemovalResult)
def remove_source(source_id: str) -> RemovalResult:
    with get_user_db() as user_conn:
        sources.ensure_sources_schema(user_conn)
        source = sources.get_source(user_conn, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Unknown source")
        removed = sources.remove_source(user_conn, source_id)
        remaining_sources = sources.list_sources(user_conn)
    with index.open_index(config.FILES_DB_PATH) as index_conn:
        unindexed = index.drop_source(index_conn, source_id)
        ancestor = sources.nearest_ancestor_source(source.path, remaining_sources)
        if ancestor is not None:
            _scan_registered_source(index_conn, ancestor, remaining_sources)
    return RemovalResult(removed=True, unindexed=unindexed)


@router.get("/api/files/browse", response_model=list[FileNode])
def browse(
    source_id: str = Query(...),
    parent: str = Query(""),
) -> list[FileNode]:
    with get_user_db() as user_conn:
        sources.ensure_sources_schema(user_conn)
        source = sources.get_source(user_conn, source_id)
        all_sources = sources.list_sources(user_conn)
        if source is None:
            raise HTTPException(status_code=404, detail="Unknown source")
    with index.open_index(config.FILES_DB_PATH) as index_conn:
        # Folders published by a module (or otherwise never scanned) are indexed
        # lazily on first browse so they aren't shown empty.
        if not index.source_is_indexed(index_conn, source_id):
            _scan_registered_source(index_conn, source, all_sources)
        entries = index.list_directory(index_conn, source_id, parent)
    return [_entry_to_node(entry) for entry in entries]


@router.post("/api/files/hash", response_model=HashProgress)
def compute_hashes(
    source_id: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
) -> HashProgress:
    """Lazily hash size-colliding files so duplicates become detectable."""
    with index.open_index(config.FILES_DB_PATH) as index_conn:
        summary = hashing.compute_missing_hashes(index_conn, source_id=source_id, limit=limit)
    return HashProgress(**summary)


@router.get("/api/files/duplicates", response_model=list[DuplicateGroup])
def list_duplicates() -> list[DuplicateGroup]:
    with index.open_index(config.FILES_DB_PATH) as index_conn:
        groups = hashing.find_duplicates(index_conn)
    return [
        DuplicateGroup(
            content_hash=group[0].content_hash or "",
            files=[_entry_to_node(entry) for entry in group],
        )
        for group in groups
    ]


@router.get("/api/files/search", response_model=list[FileNode])
def search(
    q: str = Query(..., min_length=1),
    source_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> list[FileNode]:
    source_ids: list[str] | None = None
    if source_id is not None:
        with get_user_db() as user_conn:
            sources.ensure_sources_schema(user_conn)
            source = sources.get_source(user_conn, source_id)
            if source is None:
                raise HTTPException(status_code=404, detail="Unknown source")
            all_sources = sources.list_sources(user_conn)
        source_ids = [
            source.source_id,
            *(candidate.source_id for candidate in sources.descendant_sources(source, all_sources)),
        ]
    with index.open_index(config.FILES_DB_PATH) as index_conn:
        entries = index.search_by_name(
            index_conn,
            q,
            source_ids=source_ids,
            limit=limit,
        )
    return [_entry_to_node(entry) for entry in entries]
