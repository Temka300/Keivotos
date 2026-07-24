"""Guarded local-file serving for the Files base (V1.1.1).

The base browses arbitrary user folders, so an endpoint that streams their bytes
is the one genuinely security-sensitive surface in the base
(SUITE_MODULE_CONTRACT.md section 10). Two independent dangers are handled here:

1. **Path escape.** The endpoint never accepts an absolute path — only a
   registered ``source`` plus a relative path — and then re-checks, after
   resolving symlinks, that the target still lives inside that source and
   outside Keivotos's own data tree.
2. **Active content.** Serving an arbitrary ``.html``/``.svg`` inline, on the
   app's own origin, would let that file's scripts call the local API (which can
   move and delete files). Only an explicit allowlist of inert media renders
   inline; everything else is forced to a download with ``nosniff``.

Isolated: no import of Danbooru or ``core``. The range helpers duplicate the
Danbooru media path deliberately — SUITE_MODULE_CONTRACT.md section 13 defers
extracting the genuinely shared base until both consumers exist to reveal it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote


_STREAM_CHUNK_SIZE = 1024 * 1024

# Closed allowlist: extension -> media type rendered inline. Anything absent
# (notably html, htm, svg, xml, js, and every archive/model/office format) is
# served as an attachment download instead. Subtitles and text are always
# text/plain so a mislabeled ".txt" can never execute as HTML.
_INLINE_IMAGE = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "jfif": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "avif": "image/avif",
    "bmp": "image/bmp",
}
_INLINE_VIDEO = {"mp4": "video/mp4", "webm": "video/webm", "m4v": "video/mp4"}
_INLINE_AUDIO = {
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "oga": "audio/ogg",
    "m4a": "audio/mp4",
}
_INLINE_TEXT = {"srt", "txt", "ass", "ssa", "vtt", "md", "log", "lrc"}
_INLINE_APPLICATION = {"pdf": "application/pdf"}

_DRIVE_OR_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:|[/\\])")


class ServeDenied(Exception):
    """A serve request that must be refused, carrying its HTTP status/detail."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _has_traversal_segment(relative_path: str) -> bool:
    parts = re.split(r"[/\\]", relative_path)
    return any(part == ".." for part in parts)


def resolve_within_source(
    source_root: str | Path,
    relative_path: str,
    forbidden_roots: list[Path],
) -> Path:
    """Resolve ``source_root`` + ``relative_path`` to a safe, existing path.

    Allows a file *or* a directory (annotations attach to both). Raises
    :class:`ServeDenied` with the right status on any failure. The order matters:
    reject a hostile relative path (400) before touching disk, then confirm
    containment (403) after resolving symlinks, then reject the suite's own tree
    (403), then require the path to exist (404).
    """
    if _DRIVE_OR_ABSOLUTE.match(relative_path or "") or _has_traversal_segment(relative_path):
        raise ServeDenied(400, "Path must be relative and stay inside the source")

    root = Path(source_root).expanduser().resolve(strict=False)
    resolved = (root / relative_path).resolve(strict=False)

    root_key = os.path.normcase(str(root))
    resolved_key = os.path.normcase(str(resolved))
    if resolved_key != root_key and not resolved_key.startswith(root_key + os.sep):
        # A symlink (or ``..`` that survived) pointing outside the source.
        raise ServeDenied(403, "Path escapes its source folder")

    for forbidden in forbidden_roots:
        fenced = os.path.normcase(str(Path(forbidden).expanduser().resolve(strict=False)))
        if resolved_key == fenced or resolved_key.startswith(fenced + os.sep):
            raise ServeDenied(403, "That location is not served")

    if not resolved.exists():
        raise ServeDenied(404, "File not found on disk")
    return resolved


def resolve_served_file(
    source_root: str | Path,
    relative_path: str,
    forbidden_roots: list[Path],
) -> Path:
    """Like :func:`resolve_within_source` but require a regular file (404 if not)."""
    resolved = resolve_within_source(source_root, relative_path, forbidden_roots)
    if not resolved.is_file():
        raise ServeDenied(404, "Not a file")
    return resolved


def inline_media_type(path: Path) -> tuple[str, bool]:
    """Return ``(media_type, is_inline)`` for a resolved file.

    ``is_inline`` is only true for the closed allowlist of inert media; every
    other type reports ``application/octet-stream`` and is meant to download.
    """
    ext = path.suffix.lower().lstrip(".")
    if ext in _INLINE_IMAGE:
        return _INLINE_IMAGE[ext], True
    if ext in _INLINE_VIDEO:
        return _INLINE_VIDEO[ext], True
    if ext in _INLINE_AUDIO:
        return _INLINE_AUDIO[ext], True
    if ext in _INLINE_APPLICATION:
        return _INLINE_APPLICATION[ext], True
    if ext in _INLINE_TEXT:
        return "text/plain; charset=utf-8", True
    return "application/octet-stream", False


def content_disposition(name: str, *, inline: bool) -> str:
    """Build a Content-Disposition value that survives non-ASCII filenames.

    Uses RFC 5987 ``filename*`` (so Japanese/Korean names come through) with an
    ASCII-scrubbed ``filename`` fallback. CR/LF are stripped to prevent header
    injection.
    """
    disposition = "inline" if inline else "attachment"
    safe = name.replace("\r", "").replace("\n", "").replace('"', "")
    ascii_fallback = safe.encode("ascii", "ignore").decode("ascii").strip() or "file"
    encoded = quote(safe, safe="")
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    """Parse a single ``bytes=`` range, matching the Danbooru media behavior."""
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
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = handle.read(min(_STREAM_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
