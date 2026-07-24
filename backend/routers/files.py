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
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

import config
from database import get_user_db
from files_base import annotations, attachment_store, filesystem, hashing, index, serving, sources


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
    created_at: str | None = None
    updated_at: str | None = None
    links: list[AnnotationLinkModel] = []
    attachments: list[AnnotationAttachmentModel] = []


class AnnotationRequest(BaseModel):
    source_id: str
    path: str = ""
    description: str = ""
    links: list[AnnotationLinkModel] = []


class SubjectRef(BaseModel):
    source_id: str
    path: str = ""


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


def _annotation_to_model(note: annotations.Annotation) -> AnnotationModel:
    return AnnotationModel(
        id=note.id,
        subject_kind=note.subject_kind,
        content_hash=note.content_hash,
        source_id=note.source_id,
        relative_path=note.relative_path,
        description=note.description,
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
        # A note with no text, no links, and no attachments is not worth keeping.
        if not description and not valid_links and not (existing and existing.attachments):
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


def _attachment_store_root(user_conn) -> Path:
    """Where attachment bytes live: the first Files-role source, else AppData base."""
    for source in sources.list_sources(user_conn):
        if source.role == "files":
            return Path(source.path)
    return config.BASE_HOME


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
        store_root = _attachment_store_root(user_conn)
        attachment_store.write_attachment(store_root, digest, ext, data)
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
    resolved = attachment_store.attachment_path(stored.stored_root, stored.content_hash, ext)
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
