"""Serving local media: byte ranges and the unplayable-type placeholder.

Moved verbatim from ``core.py``. Range parsing lets video and audio seek without
downloading the whole file.

The range helpers were duplicated in ``files_base/serving.py`` because the Files
base may not import module code. With both consumers settled they moved to
``services/range_serving.py`` (2026-07-25, SUITE_MODULE_CONTRACT.md section 13)
and are re-exported here, so existing importers are unaffected. No ``core``
import.
"""
from __future__ import annotations

from fastapi import Response

from services import range_serving


# Re-exported for any caller that read the constant from this module.
STREAM_CHUNK_SIZE = range_serving.STREAM_CHUNK_SIZE


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


# Re-exported so ``images_media`` keeps importing these from here. They are the
# service's objects — this module no longer carries its own copy (2026-07-25).
parse_range_header = range_serving.parse_range_header
file_range_iter = range_serving.file_range_iter
