"""Serving local media: byte ranges and the unplayable-type placeholder.

Moved verbatim from ``core.py``. Range parsing lets video and audio seek without
downloading the whole file.

Note: ``files_base/serving.py`` carries its own equivalent because the Files base
may not import module code. That duplication is deliberate for now — the shared
extraction waits until both consumers have settled
(SUITE_MODULE_CONTRACT.md section 13). No ``core`` import.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Response


STREAM_CHUNK_SIZE = 1024 * 1024


def media_placeholder(ext: str | None) -> Response:
    label = (ext or "file").upper().lstrip(".")[:6]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300" viewBox="0 0 300 300">
  <rect width="300" height="300" fill="#1e1e2e"/>
  <rect x="74" y="104" width="152" height="92" rx="12" fill="#2a2a3a"/>
  <path d="M132 126v48l42-24z" fill="#9ca3af"/>
  <text x="150" y="218" text-anchor="middle" font-family="system-ui, sans-serif" font-size="24" font-weight="700" fill="#9ca3af">{label}</text>
</svg>"""
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def parse_range_header(range_header: str | None, file_size: int) -> tuple[int, int] | None:
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
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(STREAM_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
