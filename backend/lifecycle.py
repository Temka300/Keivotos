"""Application startup, background work, and shutdown.

Suite-level startup always runs — user-database promotion, shared storage
migrations, suite schema initialization, and the recovery checkpoint. Module
storage migration and schema initialization run only for active owners. Then each
**active** surface (the base plus every enabled module) is brought online
generically through its descriptor: its folders are published, its startup hook
runs, and its background tasks are supervised. Optional-owner initialization
and worker failures are recorded without taking down the suite or Files.

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

    ``None`` fails closed for optional owners; Files still starts. A failed
    enablement lookup must not silently activate an optional module.
    """
    try:
        with get_user_db() as connection:
            suite_modules.ensure_schema(connection)
            return set(suite_modules.enabled_ids(connection))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read enabled modules; optional modules will not start: %s", exc)
        return None


class ModuleStartError(RuntimeError):
    """A recorded module failure, distinct from a busy maintenance reservation."""


class ModuleRuntime:
    """Own module tasks and failure state on the application's event loop."""

    def __init__(self):
        self.loop = asyncio.get_running_loop()
        self.tasks: dict[str, list[asyncio.Task]] = {}
        self._states: dict[str, dict] = {}
        self._state_lock = threading.Lock()

    def status(self, slug: str) -> dict:
        with self._state_lock:
            return dict(self._states.get(slug, {"state": "disabled", "error": None}))

    def _set_state(self, slug: str, state: str, error: str | None = None) -> None:
        with self._state_lock:
            self._states[slug] = {"state": state, "error": error}

    def fail(self, slug: str, stage: str, exc: Exception) -> None:
        message = f"{stage} failed; see the runtime log"
        self._set_state(slug, "failed", message)
        logger.error("Module '%s': %s: %s", slug, stage, exc,
                     exc_info=(type(exc), exc, exc.__traceback__))

    def start(self, descriptor: ModuleDescriptor) -> bool:
        if descriptor.slug in self.tasks:
            return self.status(descriptor.slug)["state"] == "running"
        self._set_state(descriptor.slug, "starting")
        tasks = self.tasks[descriptor.slug] = []
        pending = []
        try:
            with get_user_db() as connection:
                descriptor.publish(connection)
            descriptor.run_startup()
            pending = descriptor.background_tasks()
            for name, coroutine in pending:
                # Schedule the original coroutine so pre-start cancellation also
                # closes it correctly; the callback observes escaped failures.
                task = asyncio.create_task(coroutine, name=name)
                tasks.append(task)
                task.add_done_callback(lambda done, slug=descriptor.slug: self._worker_done(slug, done))
        except Exception as exc:
            self.fail(descriptor.slug, "Startup hooks", exc)
            for task in tasks:
                task.cancel()
            for _name, coroutine in pending[len(tasks):]:
                if hasattr(coroutine, "close"):
                    coroutine.close()
            return False
        self._set_state(descriptor.slug, "running")
        return True

    def _worker_done(self, slug: str, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exception = task.exception()
        if task not in self.tasks.get(slug, []):
            return
        if exception is None:
            return  # One-shot maintenance completes normally.
        if self.status(slug)["state"] in {"stopping", "disabled"}:
            logger.error("Module '%s': worker cleanup failed", slug,
                         exc_info=(type(exception), exception, exception.__traceback__))
            return
        self.fail(slug, f"Worker {task.get_name()}", exception)
        for sibling in self.tasks.get(slug, []):
            if sibling is not task and not sibling.done() and not sibling.cancelling():
                sibling.cancel()

    async def stop(self, slug: str) -> None:
        self._set_state(slug, "stopping")
        tasks = self.tasks.get(slug, [])
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.pop(slug, None)
        self._set_state(slug, "disabled")

    async def change(self, descriptor: ModuleDescriptor, enabled: bool) -> None:
        if enabled:
            if not self.start(descriptor):
                message = self.status(descriptor.slug)["error"]
                await self.stop(descriptor.slug)
                self._set_state(descriptor.slug, "failed", message)
                raise ModuleStartError(message)
        else:
            await self.stop(descriptor.slug)

    def change_from_request(self, descriptor: ModuleDescriptor, enabled: bool) -> None:
        asyncio.run_coroutine_threadsafe(self.change(descriptor, enabled), self.loop).result()


def initialize_module_storage(descriptor: ModuleDescriptor) -> None:
    if descriptor.storage_migration_hook is not None:
        descriptor.storage_migration_hook()
    init_data_db({descriptor.slug})
    init_user_db({descriptor.slug})


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
        if active is None and not descriptor.is_base:
            runtime.fail(descriptor.slug, "Enablement lookup", RuntimeError("Enabled modules could not be read"))
            continue
        if not (descriptor.is_base or descriptor.slug in active):
            logger.info("Module '%s' is disabled; skipping its startup and background work", descriptor.slug)
            continue
        try:
            if not descriptor.is_base:
                runtime._set_state(descriptor.slug, "starting")
                initialize_module_storage(descriptor)
            runtime.start(descriptor)
        except Exception as exc:
            if descriptor.is_base:
                raise
            runtime.fail(descriptor.slug, "Storage initialization", exc)

    from automatic_backups import automatic_backup_loop
    backup_stop = asyncio.Event()
    backup_task = asyncio.create_task(automatic_backup_loop(backup_stop), name="suite-automatic-backup")
    try:
        yield
    finally:
        backup_stop.set()
        # Finish an in-progress archive before shutdown; cancelling to_thread
        # would abandon a writer that continues running outside this coroutine.
        await backup_task
        module_runtime = None
        for slug in list(runtime.tasks):
            await runtime.stop(slug)
        checkpoint_task.cancel()
        with suppress(asyncio.CancelledError):
            await checkpoint_task
