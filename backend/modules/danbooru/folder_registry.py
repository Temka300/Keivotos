"""The registered-folder table read, shared by folder and tool code.

Moved verbatim from ``core.py``. A thin read over the user database's
``registered_folders`` so callers that only need the row list do not pull in the
whole compatibility facade. No ``core`` import.
"""
from __future__ import annotations

from typing import Any

from pathlib import Path

from database import get_user_db
from storage_layout import LibraryRoot


def registered_folder_rows() -> list[dict[str, Any]]:
    with get_user_db() as uconn:
        return uconn.execute(
            """SELECT name AS registration_key,
                      COALESCE(NULLIF(display_name, ''), name) AS name,
                      path, root_id
                 FROM registered_folders"""
        ).fetchall()


def library_roots() -> list[LibraryRoot]:
    return [
        LibraryRoot(str(row["root_id"]), str(row["name"]), Path(row["path"]).resolve(strict=False))
        for row in registered_folder_rows()
        if row.get("root_id") and row.get("path")
    ]
