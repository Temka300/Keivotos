"""Application startup, background work, and shutdown.

Suite-level startup always runs — user-database promotion, shared storage
migrations, suite schema initialization, and the recovery checkpoint. Module
storage migration and schema initialization run only for active owners. Then each
**active** surface (the base plus every enabled module) is brought online
generically through its descriptor: its folders are published, its startup hook
runs, and its background tasks are spawned inside catch boundaries. Storage
initialization errors still propagate; broader failure isolation is separate work.

This module names no module. A module's own startup/background code lives under
``modules/<slug>/`` and is reached only through the descriptor, which is what
keeps this file inside the enforced base/suite core (``test_module_boundaries``).
No ``core`` import.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager, suppress
from typing import AsyncGenerator

from fastapi import FastAPI

import config
import suite_modules
from config import (
    MODULE_REGISTRY,
    SUITE_HOME,
    migrate_legacy_thumbnail_cache,
    promote_legacy_module_backups,
    promote_user_database,
)
from database import get_user_db, init_data_db, init_user_db
from local_recovery import create_local_recovery_checkpoint
from module_descriptor import ModuleDescriptor
from services.default_library import install_default_library

logger = logging.getLogger(__name__)


def run_user_recovery_checkpoint() -> None:
    """Checkpoint the shared, irreplaceable user DB. Suite-level; always safe."""
    try:
        checkpoint = create_local_recovery_checkpoint("startup")
        logger.info("Local recovery checkpoint: %s", checkpoint["message"])
    except Exception as exc:  # noqa: BLE001 - recovery must not prevent startup.
        logger.warning("Local recovery checkpoint failed: %s", exc)


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


def _active_module_slugs() -> set[str] | None:
    """Enabled optional-module slugs, or ``None`` when they cannot be read.

    ``None`` is fail-open: on a read error every module is treated as active, so
    a transient fault never hides an existing library's background work (matching
    the prior Danbooru-specific fail-safe).
    """
    try:
        with get_user_db() as connection:
            suite_modules.ensure_schema(connection)
            return set(suite_modules.enabled_ids(connection))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read enabled modules; treating all as active: %s", exc)
        return None


def _bring_module_online(descriptor: ModuleDescriptor, background_tasks: list) -> None:
    """Publish, start, and spawn one active surface's work.

    Every step has its own catch boundary (contract §7). The base has no
    publish/startup/background hooks, so this is a no-op for it.
    """
    try:
        with get_user_db() as connection:
            descriptor.publish(connection)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Module '%s': folder publish failed: %s", descriptor.slug, exc)
    try:
        descriptor.run_startup()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Module '%s': startup hook failed: %s", descriptor.slug, exc)
    try:
        tasks = descriptor.background_tasks()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Module '%s': could not build background tasks: %s", descriptor.slug, exc)
        tasks = []
    for name, coro in tasks:
        background_tasks.append(asyncio.create_task(coro, name=name))


class ModuleRuntime:
    """Own each module's tasks on the application's event loop."""

    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.tasks: dict[str, list[asyncio.Task]] = {}

    def start(self, descriptor: ModuleDescriptor) -> None:
        if descriptor.slug not in self.tasks:
            tasks = []
            _bring_module_online(descriptor, tasks)
            self.tasks[descriptor.slug] = tasks

    async def stop(self, slug: str) -> None:
        tasks = self.tasks.get(slug, [])
        for task in tasks:
            task.cancel()
        # Await every worker, including thread-draining cancellation handlers.
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.pop(slug, None)

    async def change(self, descriptor: ModuleDescriptor, enabled: bool) -> None:
        if enabled:
            self.start(descriptor)
        else:
            await self.stop(descriptor.slug)

    def change_from_request(self, descriptor: ModuleDescriptor, enabled: bool) -> None:
        # Suite mutation routes are synchronous FastAPI worker-thread handlers.
        asyncio.run_coroutine_threadsafe(self.change(descriptor, enabled), self.loop).result()


module_change_lock = threading.Lock()
module_runtime: ModuleRuntime | None = None


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
    thumbnail_migration = migrate_legacy_thumbnail_cache()
    if thumbnail_migration.get("copied"):
        logger.info(
            "Warmed the thumbnail cache from the pre-v1.1.3 location: %s files copied",
            thumbnail_migration["copied"],
        )
    # Only suite-owned tables are needed to read the module enablement state.
    init_user_db(set())
    active = _active_module_slugs()
    for descriptor in MODULE_REGISTRY:
        if descriptor.is_base or active is None or descriptor.slug in active:
            if descriptor.storage_migration_hook is not None:
                descriptor.storage_migration_hook()
    init_data_db(active)
    init_user_db(active)

    # A brand-new install gets a ready-to-use Library folder beside the program.
    # Suite-level and once-only; never touches an existing library.
    install_first_run_default_library()

    # Protect the irreplaceable user DB regardless of which modules are enabled.
    checkpoint_task = asyncio.create_task(
        asyncio.to_thread(run_user_recovery_checkpoint),
        name="suite-recovery-checkpoint",
    )
    global module_runtime
    runtime = ModuleRuntime()
    module_runtime = runtime

    # Bring each active surface online — generic over the registry. A disabled
    # module contributes nothing and its background work never starts.
    for descriptor in MODULE_REGISTRY:
        if not (descriptor.is_base or active is None or descriptor.slug in active):
            logger.info("Module '%s' is disabled; skipping its startup and background work", descriptor.slug)
            continue
        runtime.start(descriptor)

    try:
        yield
    finally:
        module_runtime = None
        for slug in list(runtime.tasks):
            await runtime.stop(slug)
        checkpoint_task.cancel()
        with suppress(asyncio.CancelledError):
            await checkpoint_task
