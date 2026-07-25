"""HTTP byte-range parsing and streaming, shared by every media surface.

Extracted 2026-07-25. Both the Danbooru media path
(``modules/danbooru/media_files.py``) and the Files base
(``files_base/serving.py``) carried their own copy of this; the duplication was
deliberate while only one consumer existed, and
SUITE_MODULE_CONTRACT.md section 13 deferred the extraction until a second one
revealed the genuinely shared shape. It has.

The two copies were behaviourally identical — the only differences were a
docstring, a blank line, a local variable named ``handle`` versus ``file``, and
the chunk-size constant's name. Both used the same 1 MiB value.

This is a service, not a module: it knows nothing about Danbooru or the Files
base, only about files and byte offsets.
"""
from __future__ import annotations

from pathlib import Path


STREAM_CHUNK_SIZE = 1024 * 1024


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
    """Parse a single ``bytes=`` range into inclusive ``(start, end)`` offsets.

    Returns ``None`` for an absent, malformed, or unsatisfiable range, which
    callers treat as "serve the whole file" or answer with a 416. Only the first
    range of a multi-range request is honoured.
    """
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
    """Yield ``path``'s bytes from ``start`` to ``end`` inclusive, in chunks."""
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = handle.read(min(STREAM_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
