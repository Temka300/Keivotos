"""HTTP surface for the Files base: ``/api/files/*`` (V1.1.0).

The Files base is always-on and neutral. This router is the transport layer over
the isolated ``files_base`` engine: it registers/lists/removes sources, triggers
scans, and answers browse/search queries. It authors no metadata and never
moves or deletes files on disk (removing a source only un-indexes).

Isolation: this router does NOT ``from core import *``. It imports only the
config values it needs, the shared user-DB accessor, the standalone
``files_base`` engine, and ``thumbnails`` — which is suite-level infrastructure,
not a Danbooru import: it takes a plain path and owns only the derived WebP
cache. See docs/important/SUITE_MODULE_CONTRACT.md.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

import config
from database import get_user_db
from files_base import (
    annotations,
    archives,
    attachment_store,
    filesystem,
    hashing,
    index,
    serving,
    sources,
)
from thumbnails import DEFAULT_THUMB_SIZE, SUPPORTED_IMAGES, SUPPORTED_VIDEOS, ensure_thumbnail


MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024

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
    entry_count: int = 0


class SourceRegister(BaseModel):
    path: str
    display_name: str | None = None


class ScanSummary(BaseModel):
    added: int
    updated: int
    files: int
    directories: int
    unavailable: int


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


class AnnotationLinkModel(BaseModel):
    url: str
    label: str = ""
    kind: str = "source"


class AnnotationAttachmentModel(BaseModel):
    id: int
    content_hash: str
    file_name: str
    media_type: str
    size: int
    width: int | None = None
    height: int | None = None
    caption: str = ""
    is_cover: bool = False
    position: int = 0


class AnnotationModel(BaseModel):
    id: int
    subject_kind: str
    content_hash: str | None
    source_id: str
    relative_path: str
    description: str
    author: str = ""
    extra_info: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    links: list[AnnotationLinkModel] = []
    attachments: list[AnnotationAttachmentModel] = []


class AnnotationRequest(BaseModel):
    source_id: str
    path: str = ""
    description: str = ""
    author: str = ""
    extra_info: str = ""
    links: list[AnnotationLinkModel] = []


class SubjectRef(BaseModel):
    source_id: str
    path: str = ""


class ArchiveEntryModel(BaseModel):
    name: str
    size: int
    compressed_size: int
    is_dir: bool


class ArchiveListingModel(BaseModel):
    entries: list[ArchiveEntryModel]
    total_entries: int
    truncated: bool
    total_size: int
    compressed_size: int


class CopyInfoRequest(BaseModel):
    source: SubjectRef
    target: SubjectRef
    overwrite_description: bool = False


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


def _source_to_info(source: sources.Source, entry_count: int = 0) -> SourceInfo:
    return SourceInfo(
        source_id=source.source_id,
        path=source.path,
        display_name=source.display_name,
        role=source.role,
        visible=source.visible,
        added_at=source.added_at,
        entry_count=entry_count,
    )


def _annotation_to_model(note: annotations.Annotation) -> AnnotationModel:
    return AnnotationModel(
        id=note.id,
        subject_kind=note.subject_kind,
        content_hash=note.content_hash,
        source_id=note.source_id,
        relative_path=note.relative_path,
        description=note.description,
        author=note.author,
        extra_info=note.extra_info,
        created_at=note.created_at,
        updated_at=note.updated_at,
        links=[
            AnnotationLinkModel(url=link.url, label=link.label, kind=link.kind)
            for link in note.links
        ],
        attachments=[
            AnnotationAttachmentModel(
                id=attachment.id,
                content_hash=attachment.content_hash,
                file_name=attachment.file_name,
                media_type=attachment.media_type,
                size=attachment.size,
                width=attachment.width,
                height=attachment.height,
                caption=attachment.caption,
                is_cover=attachment.is_cover,
                position=attachment.position,
            )
            for attachment in note.attachments
        ],
    )


def _resolve_subject(source_id: str, path: str) -> tuple[sources.Source, Path]:
    """Look up the source and resolve a contained subject path (file or dir)."""
    with get_user_db() as user_conn:
        sources.ensure_sources_schema(user_conn)
        source = sources.get_source(user_conn, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Unknown source")
    try:
        resolved = serving.resolve_within_source(
            source.path, path, _forbidden_source_paths()
        )
    except serving.ServeDenied as denied:
        raise HTTPException(status_code=denied.status_code, detail=denied.detail) from denied
    return source, resolved


def _indexed_hash(resolved: Path) -> str | None:
    """A file's already-computed content hash from the index, without reading it."""
    with index.open_index(config.FILES_DB_PATH) as index_conn:
        row = index_conn.execute(
            "SELECT content_hash FROM files_index WHERE path = ?", (str(resolved),)
        ).fetchone()
    return row["content_hash"] if row is not None and row["content_hash"] else None


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
        source_list = sources.list_sources(user_conn)
    with index.open_index(config.FILES_DB_PATH) as index_conn:
        counts = {
            source.source_id: index.source_entry_count(index_conn, source.source_id)
            for source in source_list
        }
    return [_source_to_info(source, counts.get(source.source_id, 0)) for source in source_list]


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


@router.get("/api/files/file")
def serve_file(
    request: Request,
    source_id: str = Query(...),
    path: str = Query("", description="Path relative to the source root"),
):
    """Stream one file's bytes from a registered source, safely.

    The path is resolved against the source root, symlinks and traversal are
    rejected, Keivotos's own data tree is denied, and only an allowlist of inert
    media renders inline (everything else downloads with ``nosniff``). Range
    requests are supported so video/audio can seek.
    """
    with get_user_db() as user_conn:
        sources.ensure_sources_schema(user_conn)
        source = sources.get_source(user_conn, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Unknown source")

    try:
        resolved = serving.resolve_served_file(
            source.path, path, _forbidden_source_paths()
        )
    except serving.ServeDenied as denied:
        raise HTTPException(status_code=denied.status_code, detail=denied.detail) from denied

    media_type, is_inline = serving.inline_media_type(resolved)
    disposition = serving.content_disposition(resolved.name, inline=is_inline)
    base_headers = {
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": disposition,
        "Cache-Control": "private, no-cache",
    }

    file_size = resolved.stat().st_size
    range_header = request.headers.get("range")
    byte_range = serving.parse_range_header(range_header, file_size)
    if range_header and byte_range is None:
        return Response(
            status_code=416,
            headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{file_size}"},
        )

    if byte_range is not None:
        start, end = byte_range
        return StreamingResponse(
            serving.file_range_iter(resolved, start, end),
            status_code=206,
            media_type=media_type,
            headers={
                **base_headers,
                "Content-Length": str(end - start + 1),
                "Content-Range": f"bytes {start}-{end}/{file_size}",
            },
        )

    return FileResponse(resolved, media_type=media_type, headers=base_headers)


def _thumbnail_cache_key(resolved: Path, indexed: str | None = None) -> str | None:
    """A 32-hex thumbnail cache key for one file, or ``None`` if it vanished.

    The indexed content hash is preferred: it gives content-addressed dedup, so
    the same image filed in two folders — or browsed through both Files and
    Danbooru — shares one cached thumbnail. It only exists after a hash pass.

    Letting ``thumbnails`` fall back to its own MD5 would read the entire file
    just to draw a 300px tile, so a folder of multi-gigabyte videos would stall
    on first browse. Unhashed files therefore get a cheap identity/mtime/size
    key instead. It still changes whenever the file changes, and once the user
    runs a hash pass the key converges on the content hash.
    """
    if indexed is None:
        indexed = _indexed_hash(resolved)
    if indexed:
        return indexed
    try:
        stat = resolved.stat()
    except OSError:
        return None
    seed = f"{os.path.normcase(str(resolved))}:{stat.st_mtime_ns}:{stat.st_size}"
    return hashlib.md5(seed.encode("utf-8")).hexdigest()


# The index stores ``ext`` without a leading dot; ``thumbnails`` uses suffixes.
_THUMBNAILABLE_EXTS = sorted(
    ext.lstrip(".") for ext in (SUPPORTED_IMAGES | SUPPORTED_VIDEOS)
)


def _folder_cover(source_id: str, relative_path: str) -> Path | None:
    """The image a folder tile should wear, or ``None`` if it has none.

    Searches the folder's whole subtree, not just its direct children: a manga
    series' immediate children are chapter folders, so a direct-children-only
    cover would leave exactly the folders that most need one bare. Direct
    children still win, because ``parent`` sorts before ``parent/child``.

    Scoped to ``source_id``, which is what keeps the V1.1.0 boundary intact: a
    nested registered source owns its own files, so a parent folder never
    borrows a cover from a child source's contents.

    Runs as two index-friendly steps rather than one query with an ``OR``, which
    the planner cannot turn into a range (measured: it fell back to a full scan
    of the source plus a temp B-tree). Step one is an exact
    ``idx_files_index_source_parent`` hit and answers the common case.

    The descendant bound is ``rel + '/'`` .. ``rel + '0'``, never ``rel`` ..
    ``rel + '0'``: every character below ``'0'`` — ``-``, ``.``, space — would
    otherwise drag in siblings like ``rel-vol2``.
    """
    placeholders = ",".join("?" for _ in _THUMBNAILABLE_EXTS)
    common = (
        f"SELECT path FROM files_index WHERE source_id = ? AND is_dir = 0"
        f" AND available = 1 AND LOWER(ext) IN ({placeholders})"
    )
    exts: list[object] = list(_THUMBNAILABLE_EXTS)

    if relative_path:
        attempts = [
            # Direct children first: an exact index hit, and the more meaningful
            # cover — an image sitting in the folder beats one buried in it.
            (f"{common} AND parent = ? ORDER BY name COLLATE NOCASE ASC LIMIT 1",
             [source_id, *exts, relative_path]),
            (f"{common} AND parent >= ? AND parent < ?"
             " ORDER BY parent ASC, name COLLATE NOCASE ASC LIMIT 1",
             [source_id, *exts, relative_path + "/", relative_path + "0"]),
        ]
    else:
        attempts = [
            (f"{common} ORDER BY parent ASC, name COLLATE NOCASE ASC LIMIT 1",
             [source_id, *exts]),
        ]

    with index.open_index(config.FILES_DB_PATH) as index_conn:
        for query, params in attempts:
            row = index_conn.execute(query, params).fetchone()
            if row is not None:
                candidate = Path(row["path"])
                if candidate.is_file():
                    return candidate
    return None


def _attachment_cover(
    source_id: str, path: str, indexed: str | None, is_dir: bool
) -> Path | None:
    """The origin attachment a tile should wear, if the user gave it one.

    An explicit attachment **always** wins over an auto-generated thumbnail: if
    the user attached a screenshot they chose that picture, and being able to
    override a bad auto-thumbnail is the point. It is also the only way a 3D
    model, archive or document gets a face at all, which is why the info panel
    offers attachments in the first place.

    Resolution mirrors ``get_info`` — hash-first, then the unmoved-file location
    fallback — and reuses the caller's already-fetched index hash so a grid of
    unhashed files never turns into a hashing pass.
    """
    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        note = annotations.get_annotation(
            user_conn, content_hash=indexed, source_id=source_id, relative_path=path
        )
        if note is None and not is_dir and indexed is None:
            note = annotations.get_file_annotation_by_location(user_conn, source_id, path)
        if note is None or not note.attachments:
            return None
        # An explicitly flagged cover wins, then authoring order.
        chosen = min(
            note.attachments, key=lambda item: (not item.is_cover, item.position, item.id)
        )
        stored = annotations.get_attachment(user_conn, chosen.id)
    if stored is None or not stored.stored_root:
        return None
    ext = attachment_store.extension_for(stored.file_name, stored.media_type)
    candidate = attachment_store.resolve_attachment(stored.stored_root, stored.content_hash, ext)
    return candidate if candidate.is_file() else None


@router.get("/api/files/thumbnail")
def serve_file_thumbnail(
    source_id: str = Query(...),
    path: str = Query("", description="Path relative to the source root"),
    size: int = Query(DEFAULT_THUMB_SIZE, ge=DEFAULT_THUMB_SIZE, le=1200),
    v: str | None = Query(
        None, description="Client cache-busting token; ignored by the server"
    ),
):
    """Return a cached WebP thumbnail for one browsed file.

    Containment is the same chain ``serve_file`` uses — ``resolve_subject``
    rejects absolute and ``..`` paths before touching disk, re-checks that the
    target is still inside the source *after* resolving symlinks and junctions,
    and denies Keivotos's own tree.

    Precedence is: an **origin attachment** the user chose, then a **folder
    cover** from the subtree, then the file itself. The attachment wins outright
    because it is a deliberate choice and the only way an unrenderable subject —
    a 3D model, an archive, a document — gets a picture at all.

    A **directory** without an attachment answers with a cover drawn from the
    first thumbnailable file in its subtree, so a folder of manga or screenshots
    is recognisable at a glance. Whatever is chosen carries its own cache
    identity, so replacing it changes the tile.

    Unrenderable types are a deliberate 404 rather than a placeholder image:
    the placeholder is module-owned presentation, and the base falls back to its
    own type glyph in the grid instead.

    ``v`` exists because the response is ``immutable``. The server ignores it;
    the client varies it (from mtime/size) so replacing a file in place shows
    the new thumbnail instead of a cached stale one.
    """
    source, resolved = _resolve_subject(source_id, path)
    is_dir = resolved.is_dir()
    indexed = None if is_dir else _indexed_hash(resolved)

    chosen = _attachment_cover(source.source_id, path, indexed, is_dir)
    key: str | None
    if chosen is not None:
        # The attachment is its own file; it carries its own cache identity.
        key = _thumbnail_cache_key(chosen)
    elif is_dir:
        chosen = _folder_cover(source.source_id, path.strip("/").replace("\\", "/"))
        if chosen is None:
            raise HTTPException(status_code=404, detail="Folder has no cover image")
        key = _thumbnail_cache_key(chosen)
    else:
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="Not a file")
        chosen = resolved
        key = _thumbnail_cache_key(chosen, indexed)

    thumb = ensure_thumbnail(str(chosen), size, key)
    if thumb is None or not thumb.exists():
        raise HTTPException(status_code=404, detail="No thumbnail for this file type")

    return FileResponse(
        thumb,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


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


# --- User-authored annotations (origin info) -----------------------------
# A file is identified by content hash so its note survives a rename/move; a
# folder is identified by its path. A file's hash is computed here on demand,
# the moment the user enriches it (SUITE_MODULE_CONTRACT.md section 4.1).

@router.get("/api/files/info", response_model=AnnotationModel | None)
def get_info(
    source_id: str = Query(...),
    path: str = Query(""),
) -> AnnotationModel | None:
    _source, resolved = _resolve_subject(source_id, path)
    is_dir = resolved.is_dir()
    content_hash = None if is_dir else _indexed_hash(resolved)
    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        note = annotations.get_annotation(
            user_conn, content_hash=content_hash, source_id=source_id, relative_path=path
        )
        if note is None and not is_dir and content_hash is None:
            # Robust for an unmoved file whose index hash is momentarily absent.
            note = annotations.get_file_annotation_by_location(user_conn, source_id, path)
    return _annotation_to_model(note) if note is not None else None


@router.put("/api/files/info", response_model=AnnotationModel | None)
def put_info(payload: AnnotationRequest) -> AnnotationModel | None:
    _source, resolved = _resolve_subject(payload.source_id, payload.path)
    is_dir = resolved.is_dir()

    valid_links: list[dict[str, str]] = []
    for link in payload.links:
        url = link.url.strip()
        if not url:
            continue
        if not url.lower().startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400, detail=f"Only http/https links are allowed: {url}"
            )
        valid_links.append({"url": url, "label": link.label, "kind": link.kind})
    description = payload.description.strip()
    author = payload.author.strip()
    extra_info = payload.extra_info.strip()

    content_hash = None
    if not is_dir:
        # The enrich moment: hash the file once, on demand.
        with index.open_index(config.FILES_DB_PATH) as index_conn:
            content_hash = hashing.ensure_index_hash(index_conn, resolved)
        if content_hash is None:
            raise HTTPException(status_code=400, detail="Could not read the file to identify it")

    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        existing = annotations.get_annotation(
            user_conn,
            content_hash=content_hash,
            source_id=payload.source_id,
            relative_path=payload.path,
        )
        # A note with no fields, no links, and no attachments is not worth keeping.
        if (
            not description
            and not author
            and not extra_info
            and not valid_links
            and not (existing and existing.attachments)
        ):
            if existing is not None:
                annotations.delete_annotation(user_conn, existing.id)
            return None
        note = annotations.upsert_annotation(
            user_conn,
            subject_kind="dir" if is_dir else "file",
            source_id=payload.source_id,
            relative_path=payload.path,
            content_hash=content_hash,
            description=description,
            author=author,
            extra_info=extra_info,
        )
        annotations.set_links(user_conn, note.id, valid_links)
        final = annotations.get_annotation(
            user_conn,
            content_hash=content_hash,
            source_id=payload.source_id,
            relative_path=payload.path,
        )
    assert final is not None
    return _annotation_to_model(final)


@router.get("/api/files/archive", response_model=ArchiveListingModel)
def list_archive(
    source_id: str = Query(...),
    path: str = Query("", description="Path relative to the source root"),
) -> ArchiveListingModel:
    """List what is inside an archive without extracting it.

    Same containment chain as every other Files read. Strictly read-only: only
    the central directory is parsed, no member is ever decompressed, and entry
    names come back as display text that is never joined to a path. A file that
    is not really a zip is a 415, judged by content rather than by extension.
    """
    _source, resolved = _resolve_subject(source_id, path)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Not a file")

    try:
        listing = archives.list_archive(resolved)
    except archives.ArchiveUnreadable as denied:
        raise HTTPException(status_code=denied.status_code, detail=denied.detail) from denied

    return ArchiveListingModel(
        entries=[
            ArchiveEntryModel(
                name=entry.name,
                size=entry.size,
                compressed_size=entry.compressed_size,
                is_dir=entry.is_dir,
            )
            for entry in listing.entries
        ],
        total_entries=listing.total_entries,
        truncated=listing.truncated,
        total_size=listing.total_size,
        compressed_size=listing.compressed_size,
    )


@router.post("/api/files/info/copy", response_model=AnnotationModel)
def copy_info(payload: CopyInfoRequest) -> AnnotationModel:
    """Copy one subject's origin note onto another — the unzip workflow.

    Extracting an archive loses the provenance you recorded against it, so this
    carries the description, links and screenshots over to the extracted folder
    without retyping them.

    **Additive, never destructive.** Links merge as a union keyed by url+kind
    and attachments by content hash, so re-running it is a no-op rather than a
    pile of duplicates. A description is only replaced when the caller passes
    ``overwrite_description``; otherwise a target that already has text is a 409
    and the UI asks first. Nothing is ever removed from the target.

    Attachment **bytes are not copied** — the store is content-addressed, so the
    new row points at the blob that already exists.
    """
    src = payload.source
    dst = payload.target
    if src.source_id == dst.source_id and src.path == dst.path:
        raise HTTPException(status_code=400, detail="Source and target are the same subject")

    _src_source, src_resolved = _resolve_subject(src.source_id, src.path)
    _dst_source, dst_resolved = _resolve_subject(dst.source_id, dst.path)
    dst_is_dir = dst_resolved.is_dir()

    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        origin = annotations.get_annotation(
            user_conn,
            content_hash=None if src_resolved.is_dir() else _indexed_hash(src_resolved),
            source_id=src.source_id,
            relative_path=src.path,
        )
        if origin is None and not src_resolved.is_dir():
            origin = annotations.get_file_annotation_by_location(
                user_conn, src.source_id, src.path
            )
        if origin is None:
            raise HTTPException(status_code=404, detail="That file has no origin info to copy")

        existing = annotations.get_annotation(
            user_conn,
            content_hash=None if dst_is_dir else _indexed_hash(dst_resolved),
            source_id=dst.source_id,
            relative_path=dst.path,
        )
        current_text = (existing.description if existing else "").strip()
        if current_text and not payload.overwrite_description:
            raise HTTPException(
                status_code=409,
                detail="The target already has a description; copying would replace it",
            )

    # Hash the target outside the write transaction: this can read the file.
    dst_hash = None
    if not dst_is_dir:
        with index.open_index(config.FILES_DB_PATH) as index_conn:
            dst_hash = hashing.ensure_index_hash(index_conn, dst_resolved)
        if dst_hash is None:
            raise HTTPException(status_code=400, detail="Could not read the file to identify it")

    # Additive for the extra fields too: fill only what the target is missing,
    # never overwrite a value the user already put there (description keeps its
    # own 409-gated overwrite path above).
    copy_author = origin.author.strip() or None
    if copy_author and existing and existing.author.strip():
        copy_author = None
    copy_extra = origin.extra_info.strip() or None
    if copy_extra and existing and existing.extra_info.strip():
        copy_extra = None

    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        note = annotations.upsert_annotation(
            user_conn,
            subject_kind="dir" if dst_is_dir else "file",
            source_id=dst.source_id,
            relative_path=dst.path,
            content_hash=dst_hash,
            description=origin.description.strip() or None,
            author=copy_author,
            extra_info=copy_extra,
        )
        merged = [
            {"url": link.url, "label": link.label, "kind": link.kind}
            for link in annotations.list_links(user_conn, note.id)
        ]
        seen = {(link["url"], link["kind"]) for link in merged}
        for link in origin.links:
            if (link.url, link.kind) not in seen:
                merged.append({"url": link.url, "label": link.label, "kind": link.kind})
                seen.add((link.url, link.kind))
        annotations.set_links(user_conn, note.id, merged)

        held = {
            item.content_hash
            for item in annotations.list_attachments(user_conn, note.id)
        }
        for item in origin.attachments:
            if item.content_hash in held:
                continue
            stored = annotations.get_attachment(user_conn, item.id)
            if stored is None:
                continue
            annotations.add_attachment(
                user_conn,
                note.id,
                content_hash=item.content_hash,
                file_name=item.file_name,
                media_type=item.media_type,
                size=item.size,
                stored_root=stored.stored_root,
                width=item.width,
                height=item.height,
                caption=item.caption,
            )
            held.add(item.content_hash)

        final = annotations.get_annotation(
            user_conn,
            content_hash=dst_hash,
            source_id=dst.source_id,
            relative_path=dst.path,
        )
    assert final is not None
    return _annotation_to_model(final)


@router.delete("/api/files/info")
def delete_info(
    source_id: str = Query(...),
    path: str = Query(""),
) -> dict[str, bool]:
    _source, resolved = _resolve_subject(source_id, path)
    content_hash = None if resolved.is_dir() else _indexed_hash(resolved)
    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        note = annotations.get_annotation(
            user_conn, content_hash=content_hash, source_id=source_id, relative_path=path
        )
        deleted = (
            annotations.delete_annotation(user_conn, note.id) if note is not None else False
        )
    return {"deleted": deleted}


@router.get("/api/files/annotated", response_model=list[str])
def annotated_paths(source_id: str = Query(...)) -> list[str]:
    """Relative paths within a source that carry an origin note, for tile badges.

    Folder notes match by their stored path; file notes are resolved from their
    content hash back to the file's *current* index path, so a badge follows a
    move once the file is re-hashed.
    """
    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        hashes, folders = annotations.annotated_keys(user_conn)
    paths = {rel for (sid, rel) in folders if sid == source_id}
    if hashes:
        hash_list = list(hashes)
        placeholders = ",".join("?" for _ in hash_list)
        with index.open_index(config.FILES_DB_PATH) as index_conn:
            rows = index_conn.execute(
                f"SELECT relative_path FROM files_index "
                f"WHERE source_id = ? AND content_hash IN ({placeholders})",
                [source_id, *hash_list],
            ).fetchall()
        paths.update(row["relative_path"] for row in rows)
    return sorted(paths)


def _attachment_store_root() -> Path:
    """Where new attachment bytes are written: the configured folder, else the
    Files base home. Existing attachments resolve from their own stored root."""
    return config.attachment_store_root()


def _subject_content_hash(resolved: Path, is_dir: bool) -> str | None:
    if is_dir:
        return None
    with index.open_index(config.FILES_DB_PATH) as index_conn:
        digest = hashing.ensure_index_hash(index_conn, resolved)
    if digest is None:
        raise HTTPException(status_code=400, detail="Could not read the file to identify it")
    return digest


@router.post("/api/files/attachment", response_model=AnnotationModel)
async def upload_attachment(
    request: Request,
    source_id: str = Query(...),
    path: str = Query(""),
    file_name: str = Query(...),
    caption: str = Query(""),
) -> AnnotationModel:
    """Attach an uploaded image/video to a subject's origin note.

    The raw bytes are the request body (no multipart dependency); the type comes
    from ``Content-Type``. Bytes are stored content-addressed inside the first
    Files folder; identical uploads are de-duplicated.
    """
    media_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if not (media_type.startswith("image/") or media_type.startswith("video/")):
        raise HTTPException(status_code=400, detail="Only image or video attachments are allowed")
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="Attachment exceeds the 50 MB limit")

    _source, resolved = _resolve_subject(source_id, path)
    is_dir = resolved.is_dir()
    content_hash = _subject_content_hash(resolved, is_dir)

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="Attachment exceeds the 50 MB limit")

    digest = attachment_store.md5_bytes(data)
    ext = attachment_store.extension_for(file_name, media_type)
    width, height = (
        attachment_store.image_dimensions(data) if media_type.startswith("image/") else (None, None)
    )

    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        sources.ensure_sources_schema(user_conn)
        store_root = _attachment_store_root()
        visible = config.attachment_store_mode() == "folder"
        attachment_store.write_attachment(store_root, digest, ext, data, visible=visible)
        note = annotations.upsert_annotation(
            user_conn,
            subject_kind="dir" if is_dir else "file",
            source_id=source_id,
            relative_path=path,
            content_hash=content_hash,
        )
        annotations.add_attachment(
            user_conn,
            note.id,
            content_hash=digest,
            file_name=file_name,
            media_type=media_type,
            size=len(data),
            stored_root=str(store_root),
            width=width,
            height=height,
            caption=caption,
        )
        final = annotations.get_annotation(
            user_conn, content_hash=content_hash, source_id=source_id, relative_path=path
        )
    assert final is not None
    return _annotation_to_model(final)


@router.get("/api/files/attachment/{attachment_id}")
def serve_attachment(attachment_id: int, request: Request):
    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        stored = annotations.get_attachment(user_conn, attachment_id)
    if stored is None or not stored.stored_root:
        raise HTTPException(status_code=404, detail="Attachment not found")
    ext = attachment_store.extension_for(stored.file_name, stored.media_type)
    resolved = attachment_store.resolve_attachment(stored.stored_root, stored.content_hash, ext)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="Attachment bytes are missing")

    headers = {
        "Accept-Ranges": "bytes",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": serving.content_disposition(stored.file_name, inline=True),
        "Cache-Control": "private, max-age=3600",
    }
    file_size = resolved.stat().st_size
    byte_range = serving.parse_range_header(request.headers.get("range"), file_size)
    if request.headers.get("range") and byte_range is None:
        return Response(
            status_code=416,
            headers={"Accept-Ranges": "bytes", "Content-Range": f"bytes */{file_size}"},
        )
    if byte_range is not None:
        start, end = byte_range
        return StreamingResponse(
            serving.file_range_iter(resolved, start, end),
            status_code=206,
            media_type=stored.media_type,
            headers={
                **headers,
                "Content-Length": str(end - start + 1),
                "Content-Range": f"bytes {start}-{end}/{file_size}",
            },
        )
    return FileResponse(resolved, media_type=stored.media_type, headers=headers)


@router.delete("/api/files/attachment/{attachment_id}")
def delete_attachment(attachment_id: int) -> dict[str, bool]:
    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        stored = annotations.get_attachment(user_conn, attachment_id)
        if stored is None:
            return {"deleted": False}
        removed = annotations.remove_attachment(user_conn, stored.annotation_id, attachment_id)
        orphaned = removed and annotations.attachment_hash_refcount(user_conn, stored.content_hash) == 0
        if removed:
            annotations.prune_if_empty(user_conn, stored.annotation_id)
    if orphaned and stored.stored_root:
        ext = attachment_store.extension_for(stored.file_name, stored.media_type)
        attachment_store.delete_attachment_file(stored.stored_root, stored.content_hash, ext)
    return {"deleted": bool(removed)}


class AttachmentStoreInfo(BaseModel):
    path: str
    mode: str
    is_default: bool
    default: str


class AttachmentStoreRequest(BaseModel):
    path: str | None = None


def _attachment_store_info() -> AttachmentStoreInfo:
    effective = config.attachment_store_root()
    default = config.BASE_HOME
    return AttachmentStoreInfo(
        path=str(effective),
        mode=config.attachment_store_mode(),
        is_default=effective.resolve(strict=False) == default.resolve(strict=False),
        default=str(default),
    )


@router.get("/api/files/attachment-store", response_model=AttachmentStoreInfo)
def get_attachment_store() -> AttachmentStoreInfo:
    """Where origin-note attachment images/videos are stored."""
    return _attachment_store_info()


class AttachmentMigrateResult(BaseModel):
    migrated: int
    skipped: int


@router.post("/api/files/attachment-store/migrate", response_model=AttachmentMigrateResult)
def migrate_attachments_to_folder() -> AttachmentMigrateResult:
    """Copy existing attachments into the current visible folder store and repoint them.

    Only valid in folder mode. Non-destructive: bytes are copied (deduped) into
    ``<folder>/Attachments/`` and each row is repointed there, so previously hidden
    attachments become browsable in Files. The old managed copy is left untouched.
    """
    if config.attachment_store_mode() != "folder":
        raise HTTPException(status_code=400, detail="Choose a folder store first, then migrate.")
    target_root = config.attachment_store_root()
    migrated = 0
    skipped = 0
    with get_user_db() as user_conn:
        annotations.ensure_annotations_schema(user_conn)
        rows = annotations.list_all_attachments(user_conn)
        for row in rows:
            if not row.stored_root:
                skipped += 1
                continue
            ext = attachment_store.extension_for(row.file_name, row.media_type)
            target = attachment_store.attachment_path(target_root, row.content_hash, ext, visible=True)
            if target.is_file():
                # Already visible under the target store; just make sure the row agrees.
                if row.stored_root != str(target_root):
                    annotations.update_attachment_stored_root(user_conn, row.id, str(target_root))
                    migrated += 1
                else:
                    skipped += 1
                continue
            current = attachment_store.resolve_attachment(row.stored_root, row.content_hash, ext)
            if not current.is_file():
                skipped += 1
                continue
            attachment_store.write_attachment(
                target_root, row.content_hash, ext, current.read_bytes(), visible=True
            )
            annotations.update_attachment_stored_root(user_conn, row.id, str(target_root))
            migrated += 1
    return AttachmentMigrateResult(migrated=migrated, skipped=skipped)


@router.put("/api/files/attachment-store", response_model=AttachmentStoreInfo)
def set_attachment_store(payload: AttachmentStoreRequest) -> AttachmentStoreInfo:
    """Point the attachment store at a folder, or reset to the default (empty path).

    Non-destructive: only new attachments follow this; existing ones resolve from
    their own recorded location.
    """
    raw = (payload.path or "").strip()
    if not raw:
        config.set_attachment_store_root(None)
        return _attachment_store_info()

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise HTTPException(status_code=400, detail="Choose a full folder path")
    anchor = Path(candidate.anchor).resolve(strict=False) if candidate.anchor else None
    if anchor is not None and candidate.resolve(strict=False) == anchor:
        raise HTTPException(status_code=400, detail="Choose a specific folder, not a drive root")
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Cannot use that folder: {exc}") from exc
    if not os.access(candidate, os.W_OK):
        raise HTTPException(status_code=400, detail="That folder is not writable")

    config.set_attachment_store_root(str(candidate))
    return _attachment_store_info()


@router.post("/api/files/open")
def open_file(payload: SubjectRef) -> dict[str, str]:
    """Open the subject in the OS default application."""
    _source, resolved = _resolve_subject(payload.source_id, payload.path)
    try:
        if sys.platform == "win32":
            os.startfile(str(resolved))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(resolved)])
        else:
            subprocess.Popen(["xdg-open", str(resolved)])
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to open: {exc}") from exc
    return {"status": "opened"}


@router.post("/api/files/reveal")
def reveal_file(payload: SubjectRef) -> dict[str, str]:
    """Reveal the subject in the OS file manager (select it in its folder)."""
    _source, resolved = _resolve_subject(payload.source_id, payload.path)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer.exe", "/select,", str(resolved)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(resolved)])
        else:
            subprocess.Popen(["xdg-open", str(resolved.parent)])
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to reveal: {exc}") from exc
    return {"status": "revealed"}
