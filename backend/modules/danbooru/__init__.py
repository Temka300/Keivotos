"""Descriptor and publication hook for the Danbooru module."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from files_base import sources
from module_descriptor import BackupComponent, ModuleDescriptor
from modules.danbooru.configuration import configuration_defaults


def publish_sources(user_connection: sqlite3.Connection) -> None:
    """Project Danbooru-owned folders into the shared Files registry."""
    sources.ensure_sources_schema(user_connection)
    rows = user_connection.execute(
        "SELECT path, display_name FROM registered_folders WHERE path IS NOT NULL AND path<>''"
    ).fetchall()
    folders = [(str(row["path"]), row["display_name"]) for row in rows]
    sources.reconcile_module_sources(user_connection, "danbooru", folders)
    for path, _name in folders:
        source = sources.get_source(user_connection, sources.deterministic_source_id(path))
        if source is not None:
            user_connection.execute(
                "UPDATE registered_folders SET display_name=? WHERE path=?",
                (source.display_name, path),
            )
    user_connection.commit()


def adopt_source(source_id: str) -> dict[str, object]:
    # Lazy import avoids pulling the legacy Danbooru facade into suite startup.
    from modules.danbooru.routers.folders import adopt_shared_source

    return adopt_shared_source(source_id)


def release_source(source_id: str, forget: bool = False) -> dict[str, object]:
    from modules.danbooru.routers.folders import release_shared_source

    return release_shared_source(source_id, forget=forget)


def folder_preview(source_id: str) -> dict[str, object]:
    from modules.danbooru.routers.folders import shared_source_release_preview

    return shared_source_release_preview(source_id)


def update_folder(source_id: str) -> None:
    from modules.danbooru.routers.folders import update_shared_source_presentation

    update_shared_source_presentation(source_id)


def rescan_source(source_id: str) -> dict[str, object]:
    from modules.danbooru.routers.folders import rescan_shared_source

    return rescan_shared_source(source_id)


def relocate_source(source_id: str, new_path: str) -> dict[str, object]:
    from modules.danbooru.routers.folders import relocate_shared_source

    return relocate_shared_source(source_id, new_path)


def _routers() -> list:
    """Danbooru's HTTP surface, imported lazily at app-composition time.

    Module routers live under ``modules/danbooru/routers`` with unchanged URLs.
    Suite maintenance endpoints are mounted independently by the shell.
    """
    from modules.danbooru.routers import artists, collections, discovery, folders, images_media, stats, tags, user_library
    from modules.danbooru.routers import tools

    return [
        images_media.router,
        discovery.router,
        tags.router,
        artists.router,
        folders.router,
        user_library.router,
        collections.router,
        tools.router,
        stats.router,
    ]


def _background_tasks() -> list:
    """Danbooru's lifetime background work, imported lazily at startup."""
    from modules.danbooru.lifecycle import background_tasks

    return background_tasks()


def _initialize_index(database_path, connection_factory) -> None:
    from modules.danbooru.index_migrations import initialize_index

    initialize_index(database_path, connection_factory)


def _user_schema() -> str:
    from modules.danbooru.user_schema import USER_SCHEMA

    return USER_SCHEMA


def _migrate_user_tables(connection, database_path: Path, media_root: Path) -> None:
    from modules.danbooru.user_schema import migrate_user_tables

    migrate_user_tables(connection, database_path, media_root)


def _migrate_storage() -> None:
    import logging
    from config import migrate_legacy_default_metadata

    migration = migrate_legacy_default_metadata()
    if migration["migrated"]:
        logging.getLogger(__name__).info(
            "Flattened legacy metadata directory: %s moved, %s identical duplicates removed",
            migration["moved"], migration["deduplicated"],
        )


def _backup_components() -> tuple[BackupComponent, ...]:
    from config import DATA_DB_PATH, SIDECAR_DIR, METADATA_DIR, ARTIST_PROFILE_ARCHIVE_DIR

    return (
        BackupComponent("library_database", "danbooru", "databases/danbooru.sqlite", "sqlite", DATA_DB_PATH),
        BackupComponent("sidecars", "danbooru", "sidecars", "tree", SIDECAR_DIR),
        BackupComponent("sidecar_history", "danbooru", "sidecar_archive", "tree", METADATA_DIR / "sidecar_archive"),
        BackupComponent("artist_profile_archive", "danbooru", "artist_profile_archive", "tree", ARTIST_PROFILE_ARCHIVE_DIR),
    )


def descriptor(suite_home: Path, version: str) -> ModuleDescriptor:
    home = suite_home / "modules" / "danbooru"
    return ModuleDescriptor(
        slug="danbooru",
        name="Danbooru",
        description="Browse your image library with Danbooru tags and metadata.",
        home=home,
        database=home / "danbooru.sqlite",
        credentials=home / "danbooru_credentials.json",
        api_prefix="/api/danbooru",
        log_prefix="danbooru",
        user_agent=f"Keivotos/{version} (Danbooru)",
        disableable=True,
        is_base=False,
        config_defaults=configuration_defaults(home),
        backup_components_provider=_backup_components,
        storage_migration_hook=_migrate_storage,
        publish_hook=publish_sources,
        adopt_hook=adopt_source,
        release_hook=release_source,
        folder_preview_hook=folder_preview,
        folder_update_hook=update_folder,
        rescan_hook=rescan_source,
        relocate_hook=relocate_source,
        router_provider=_routers,
        background_tasks_hook=_background_tasks,
        index_initializer=_initialize_index,
        user_schema_provider=_user_schema,
        user_migrator=_migrate_user_tables,
    )
