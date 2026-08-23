"""Danbooru's startup and background work, owned by the module.

The suite lifespan runs this through the module descriptor's background-tasks
hook, and only when Danbooru is enabled. Moving it here from the suite
``lifecycle`` is what lets that lifespan stay module-agnostic and rejoin the
enforced base/suite core (no ``modules.*`` import) — the boundary the
``test_module_boundaries`` tripwire protects.

``automation`` still lives at the backend top level (it is imported by
``routers/tools.py`` too); relocating it under this module is v1.1.6 Danbooru
modularization, not this framework slice.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from automation import automation_loop
from config import DATA_ROOT, SIDECAR_DIR
from database import get_data_db
from modules.danbooru.folder_registry import library_roots
from storage_layout import migrate_existing_sidecars

logger = logging.getLogger(__name__)

SIDECAR_LAYOUT_MIGRATION_KEY = "sidecar_layout_v2_complete"


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


def background_tasks() -> list[tuple[str, object]]:
    """Danbooru's lifetime background work: the one-shot sidecar migration and
    the auto-ingest watcher. Coroutines are constructed here (only when the
    module is active) and spawned as tasks by the suite lifespan."""
    return [
        ("danbooru-sidecar-migration", asyncio.to_thread(run_sidecar_layout_migration)),
        ("danbooru-auto-ingest", automation_loop()),
    ]
