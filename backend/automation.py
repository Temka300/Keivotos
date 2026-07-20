"""Low-frequency, local-only watcher for new or changed external media."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import get_automation_config, save_config
from thumbnails import SUPPORTED_IMAGES, SUPPORTED_VIDEOS

MEDIA_EXTENSIONS = SUPPORTED_IMAGES | SUPPORTED_VIDEOS
logger = logging.getLogger(__name__)

_state_lock = threading.Lock()
_last_run_at: str | None = None
_candidate_count = 0


def find_changed_media_candidates(
    roots: list[str | Path],
    manifest: dict[str, tuple[int | None, int | None]],
) -> list[Path]:
    """Return files missing from the manifest or whose stat signature changed."""
    found: list[Path] = []
    seen: set[str] = set()
    for raw_root in roots:
        root = Path(raw_root).resolve(strict=False)
        if not root.is_dir():
            continue
        stack = [root]
        while stack:
            directory = stack.pop()
            try:
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            path = Path(entry.path)
                            if path.suffix.lower() not in MEDIA_EXTENSIONS:
                                continue
                            key = os.path.normcase(os.path.abspath(entry.path))
                            if key in seen:
                                continue
                            seen.add(key)
                            stat = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if manifest.get(key) != (stat.st_mtime_ns, stat.st_size):
                            found.append(path)
            except OSError:
                continue
    return sorted(found, key=lambda item: str(item).casefold())


def automation_status() -> dict:
    config = get_automation_config()
    with _state_lock:
        return {
            "enabled": config["enabled"],
            "enabled_at": config["enabled_at"],
            "interval_minutes": config["interval_minutes"],
            "last_run_at": _last_run_at,
            "candidate_count": _candidate_count,
        }


def set_automation_enabled(enabled: bool, interval_minutes: int | None = None) -> dict:
    current = get_automation_config()
    updates: dict[str, object] = {"automation_enabled": enabled}
    if interval_minutes is not None:
        updates["automation_interval_minutes"] = max(5, min(1440, int(interval_minutes)))
    if enabled and not current["enabled"]:
        updates["automation_enabled_at"] = datetime.now(timezone.utc).isoformat()
    save_config(updates)
    if not enabled:
        global _candidate_count
        with _state_lock:
            _candidate_count = 0
    return automation_status()


def run_automation_tick() -> dict:
    """Scan once and launch a local-only incremental import when needed."""
    config = get_automation_config()
    if not config["enabled"] or not config["enabled_at"]:
        return automation_status()

    # Imported lazily to avoid a module cycle: core owns the shared tool lock
    # and imports automation_loop for its FastAPI lifespan.
    import core

    try:
        operation = core.exclusive_tool_operation("running an automatic library check")
        with operation:
            roots = core._sync_scan_paths()
            manifest: dict[str, tuple[int | None, int | None]] = {}
            with core.get_data_db() as connection:
                try:
                    for row in connection.execute("SELECT media_path, media_mtime, media_size FROM sync_manifest"):
                        manifest[os.path.normcase(str(row["media_path"]))] = (row["media_mtime"], row["media_size"])
                except Exception:
                    manifest = {}
            candidates = find_changed_media_candidates(roots, manifest)
            now = datetime.now(timezone.utc).isoformat()
            global _last_run_at, _candidate_count
            with _state_lock:
                _last_run_at = now
                _candidate_count = len(candidates)

            if candidates:
                core._launch_tool(
                    "sync",
                    [core._sync_command(roots)],
                    stage_names=["Sync new and changed files"],
                )
    except RuntimeError:
        return automation_status()
    return automation_status()


async def automation_loop() -> None:
    """Run once on startup, then reconcile at the user-selected interval."""
    while True:
        try:
            await asyncio.to_thread(run_automation_tick)
        except Exception:  # noqa: BLE001 - the next tick must remain available.
            logger.exception("Automatic library ingest tick failed")
        interval = get_automation_config()["interval_minutes"]
        await asyncio.sleep(interval * 60)
