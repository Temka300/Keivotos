"""Application startup, background work, and shutdown.

Moved verbatim from ``core.py``. Suite-level startup always runs — user-database
promotion, legacy layout migrations, schema initialization, and the recovery
checkpoint. Danbooru's background work (the sidecar file-walk and the auto-ingest
watcher) is gated on the module being enabled, so the suite boots without it.

Every maintenance step swallows its own failure and logs it: startup must not be
blocked by an optional migration. No ``core`` import.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI

import config
import suite_modules
from automation import automation_loop
from config import (
    DANBOORU_SLUG,
    DATA_ROOT,
    MODULE_REGISTRY,
    SIDECAR_DIR,
    SUITE_HOME,
    migrate_legacy_default_metadata,
    promote_legacy_module_backups,
    promote_user_database,
)
from database import get_data_db, get_user_db, init_data_db, init_user_db
from local_recovery import create_local_recovery_checkpoint
from modules.danbooru.folder_registry import library_roots
from services.default_library import install_default_library
from storage_layout import migrate_existing_sidecars

logger = logging.getLogger(__name__)


SIDECAR_LAYOUT_MIGRATION_KEY = "sidecar_layout_v2_complete"


def run_user_recovery_checkpoint() -> None:
    """Checkpoint the shared, irreplaceable user DB. Suite-level; always safe."""
    try:
        checkpoint = create_local_recovery_checkpoint("startup")
        logger.info("Local recovery checkpoint: %s", checkpoint["message"])
    except Exception as exc:  # noqa: BLE001 - recovery must not prevent startup.
        logger.warning("Local recovery checkpoint failed: %s", exc)


def run_sidecar_layout_migration() -> None:
    """Danbooru-only: fold legacy sidecars into the canonical layout, once."""
    try:
        with get_data_db() as migration_connection:
            completed = migration_connection.execute(
                "SELECT value FROM metadata WHERE key=?",
                (SIDECAR_LAYOUT_MIGRATION_KEY,),
            ).fetchone()
            if completed:
                return
            media_paths = [Path(row["path"]) for row in migration_connection.execute("SELECT path FROM files")]

        migration_result = migrate_existing_sidecars(
            media_paths,
            DATA_ROOT,
            SIDECAR_DIR,
            library_roots(),
        )
        if migration_result["copied"] or migration_result["failed"]:
            logger.info("Sidecar layout migration: %s", migration_result)

        if not migration_result["failed"]:
            with get_data_db() as migration_connection:
                migration_connection.execute(
                    "INSERT INTO metadata(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (SIDECAR_LAYOUT_MIGRATION_KEY, datetime.now(timezone.utc).isoformat()),
                )
                migration_connection.commit()
    except Exception as exc:  # noqa: BLE001 - maintenance must not break the running app.
        logger.warning("Sidecar layout migration failed: %s", exc)


def run_startup_maintenance() -> None:
    """Compatibility wrapper: suite recovery checkpoint + Danbooru sidecar migration."""
    run_user_recovery_checkpoint()
    run_sidecar_layout_migration()


def install_first_run_default_library() -> None:
    """Give a brand-new install a ready-to-use ``Library`` folder beside the program.

    Suite-level and always-on (no module dependency). Runs once, gated by a
    config flag, so removing the folder in Manage folders never recreates it and
    an existing library is never touched. Fail-safe: any error is logged and the
    flag is left unset so the next start can retry.
    """
    if not config.default_library_pending():
        return
    try:
        with get_user_db() as user_conn:
            source = install_default_library(
                user_conn,
                config.first_run_library_dir(),
                forbidden_paths=[SUITE_HOME],
            )
        if source is not None:
            logger.info("Created first-run default library: %s", source.path)
    except Exception as exc:  # noqa: BLE001 - startup must not be blocked.
        logger.warning("Could not create the first-run default library: %s", exc)
        return
    config.mark_default_library_created()


def reconcile_module_folders() -> None:
    """Let every registered module publish its folders into the shared list.

    A module keeps its own storage as the source of truth and mirrors the
    folders it owns into the base browse-list under its own role, pruning stale
    rows for that role. Self-healing: catches any register/remove hook that
    didn't fire. Module -> base only, never the reverse.

    The base has no publish hook, so iterating the whole registry is a no-op for
    it and no module is named here.
    """
    try:
        with get_user_db() as connection:
            for descriptor in MODULE_REGISTRY:
                descriptor.publish(connection)
    except Exception as exc:  # noqa: BLE001 - never block startup.
        logger.warning("Could not reconcile module folders into the Files base: %s", exc)


def danbooru_module_enabled() -> bool:
    """Whether the Danbooru module is enabled in the shared user DB.

    Returns False when the module is not registered at all, so a suite built
    without it never starts Danbooru's background work.

    Fail-safe: if the enabled set cannot be read, assume enabled so an existing
    library is never hidden by a transient error.
    """
    descriptor = MODULE_REGISTRY.get(DANBOORU_SLUG)
    if descriptor is None:
        return False
    try:
        with get_user_db() as connection:
            suite_modules.ensure_schema(connection)
            return descriptor.slug in suite_modules.enabled_ids(connection)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read enabled modules; assuming Danbooru enabled: %s", exc)
        return True


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Suite-level startup — always runs, independent of any module.
    promotion = promote_user_database()
    if promotion.get("promoted"):
        logger.info("Promoted user database to suite root: %s", promotion["destination"])
    backup_promotion = promote_legacy_module_backups()
    if backup_promotion.get("promoted"):
        logger.info(
            "Copied and verified %s legacy module backups into the suite backup directory; source preserved",
            backup_promotion["files"],
        )
    migration = migrate_legacy_default_metadata()
    if migration["migrated"]:
        logger.info(
            "Flattened legacy metadata directory: %s moved, %s identical duplicates removed",
            migration["moved"],
            migration["deduplicated"],
        )
    init_data_db()
    init_user_db()

    # A brand-new install gets a ready-to-use Library folder beside the program.
    # Suite-level and once-only; never touches an existing library.
    install_first_run_default_library()

    # Protect the irreplaceable user DB regardless of which modules are enabled.
    checkpoint_task = asyncio.create_task(
        asyncio.to_thread(run_user_recovery_checkpoint),
        name="suite-recovery-checkpoint",
    )
    background_tasks = [checkpoint_task]

    # Danbooru's background work (sidecar file-walk + the auto-ingest watcher)
    # runs only when the module is enabled — the app boots without it otherwise.
    if danbooru_module_enabled():
        reconcile_module_folders()
        sidecar_task = asyncio.create_task(
            asyncio.to_thread(run_sidecar_layout_migration),
            name="danbooru-sidecar-migration",
        )
        automation_task = asyncio.create_task(automation_loop(), name="danbooru-auto-ingest")
        background_tasks += [sidecar_task, automation_task]
    else:
        logger.info("Danbooru module not enabled; skipping its background startup")

    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        for task in background_tasks:
            with suppress(asyncio.CancelledError):
                await task
