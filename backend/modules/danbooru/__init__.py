"""Descriptor and publication hook for the Danbooru module."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from files_base import sources
from module_descriptor import ModuleDescriptor


def publish_sources(user_connection: sqlite3.Connection) -> None:
    """Project Danbooru-owned folders into the shared Files registry."""
    sources.ensure_sources_schema(user_connection)
    rows = user_connection.execute(
        "SELECT path, display_name FROM registered_folders WHERE path IS NOT NULL AND path<>''"
    ).fetchall()
    folders = [(str(row["path"]), row["display_name"]) for row in rows]
    sources.reconcile_module_sources(user_connection, "danbooru", folders)


def adopt_source(source_id: str) -> dict[str, object]:
    # Lazy import avoids pulling the legacy Danbooru facade into suite startup.
    from routers.folders import adopt_shared_source

    return adopt_shared_source(source_id)


def release_source(source_id: str, forget: bool = False) -> dict[str, object]:
    from routers.folders import release_shared_source

    return release_shared_source(source_id, forget=forget)


def folder_preview(source_id: str) -> dict[str, object]:
    from routers.folders import shared_source_release_preview

    return shared_source_release_preview(source_id)


def update_folder(source_id: str) -> None:
    from routers.folders import update_shared_source_presentation

    update_shared_source_presentation(source_id)


def rescan_source(source_id: str) -> dict[str, object]:
    from routers.folders import rescan_shared_source

    return rescan_shared_source(source_id)


def relocate_source(source_id: str, new_path: str) -> dict[str, object]:
    from routers.folders import relocate_shared_source

    return relocate_shared_source(source_id, new_path)


def descriptor(suite_home: Path, version: str) -> ModuleDescriptor:
    home = suite_home / "modules" / "danbooru"
    return ModuleDescriptor(
        slug="danbooru",
        name="Danbooru",
        home=home,
        database=home / "danbooru.sqlite",
        credentials=home / "danbooru_credentials.json",
        api_prefix="/api/danbooru",
        log_prefix="danbooru",
        user_agent=f"Keivotos/{version} (Danbooru)",
        disableable=True,
        is_base=False,
        publish_hook=publish_sources,
        adopt_hook=adopt_source,
        release_hook=release_source,
        folder_preview_hook=folder_preview,
        folder_update_hook=update_folder,
        rescan_hook=rescan_source,
        relocate_hook=relocate_source,
    )
