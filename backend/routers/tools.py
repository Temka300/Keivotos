from __future__ import annotations

import base64
import json
import sqlite3
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from automation import automation_status, set_automation_enabled
from backup_bundle import (
    backup_configuration,
    backup_estimate,
    create_backup_bundle,
    inspect_backup_bundle,
    restore_backup_bundle,
    update_backup_configuration,
)
from config import get_backup_config, public_storage_config, save_config
from core import *  # shared query, database, and media helpers
from local_recovery import create_local_recovery_checkpoint, local_recovery_status
from models import (
    AutomationStatus,
    AutomationUpdate,
    BackupConfigurationUpdate,
    BackupCreateRequest,
    BackupRestoreRequest,
    ImportRunRequest,
    ThumbnailCacheLimitUpdate,
    ToolStatusInfo,
)
from thumbnails import cleanup_thumbnail_cache, clear_thumbnail_cache, prune_thumbnail_cache, thumbnail_cache_status, thumbnail_cache_token
from tag_history import record_removed_tags_from_archive

router = APIRouter()


TOOL_DEFINITIONS = [
    {
        "id": "sync",
        "name": "Sync Database",
        "description": "Incrementally index new, changed, and removed images across all configured folders. Unchanged files are skipped.",
        "command": "danbooru_gallery_dl.py sync <all folders>",
    },
    {
        "id": "backfill",
        "name": "Backfill Metadata",
        "description": "Fetch Danbooru tags and metadata for existing local images by MD5 and create missing central sidecars.",
        "command": "danbooru_gallery_dl.py backfill <configured folders>",
        "requires_form": True,
    },
    {
        "id": "sqlite",
        "name": "Rebuild Database (Recovery)",
        "description": "Fully rebuild the SQLite image database from sidecars, then recreate its sync manifest. Use only for recovery.",
        "command": "danbooru_gallery_dl.py sqlite --replace; sync",
    },
    {
        "id": "clean-sidecars",
        "name": "Clean Orphan Sidecars",
        "description": "Remove central sidecars whose original image or video no longer exists.",
        "command": "danbooru_gallery_dl.py clean-sidecars",
    },
    {
        "id": "refresh-tags",
        "name": "Update Danbooru Tags",
        "description": "Re-fetch current Danbooru metadata, archive replaced sidecars, then sync the updated tags into SQLite. Local user tags are untouched.",
        "command": "danbooru_gallery_dl.py backfill --overwrite --archive-replaced-sidecars; sync",
    },
]


def _tool_payload(definition: dict[str, Any]) -> dict[str, Any]:
    result = dict(definition)
    task = tool_task_snapshot(definition["id"])
    if task:
        result.update(task)
    else:
        result.update({"status": "idle", "output": "", "progress": 0, "total": 0})
    return result


@router.get("/api/tools", response_model=list[ToolInfo])
def list_tools():
    return [_tool_payload(tool) for tool in TOOL_DEFINITIONS]


@router.get("/api/automation", response_model=AutomationStatus)
def get_automation():
    return automation_status()


@router.put("/api/automation", response_model=AutomationStatus)
def update_automation(update: AutomationUpdate):
    return set_automation_enabled(update.enabled, update.interval_minutes)


@router.get("/api/storage")
def storage_configuration():
    return public_storage_config()


def _import_phase_counts() -> dict[str, int]:
    with get_data_db() as connection:
        row = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM files) AS total,
                COALESCE(SUM(discovered_at IS NOT NULL), 0) AS discovered,
                COALESCE(SUM(enriched_at IS NOT NULL), 0) AS enriched,
                COALESCE(SUM(metadata_at IS NOT NULL), 0) AS metadata,
                COALESCE(SUM(finalized_at IS NOT NULL), 0) AS finalized,
                COALESCE(SUM(status = 'error'), 0) AS errors,
                COALESCE(SUM(status = 'no_match'), 0) AS no_match
            FROM ingest_state
            """
        ).fetchone()
    return {key: int(row[key]) for key in ("total", "discovered", "enriched", "metadata", "finalized", "errors", "no_match")}


@router.get("/api/import-pipeline")
def import_pipeline_status():
    task = tool_task_snapshot("import") or {"status": "idle", "output": "", "progress": 0, "total": 0}
    return {"phases": _import_phase_counts(), "task": task}


@router.get("/api/import-pipeline/task", response_model=ToolStatusInfo)
def import_pipeline_task(after_index: int | None = Query(None, ge=0)):
    task = tool_task_snapshot("import")
    if not task:
        return {"status": "idle", "output": "", "progress": 0, "total": 0}
    payload = dict(task)
    if after_index is not None:
        payload["file_results"] = [
            result
            for result in task.get("file_results", [])
            if result.get("index") is None or int(result["index"]) > after_index
        ]
    return payload


@router.post("/api/import-pipeline/run")
def run_import(request: ImportRunRequest):
    phase = request.phase.strip().lower()
    if phase not in {"discover", "enrich", "metadata", "finalize", "all"}:
        raise HTTPException(400, "Unknown import phase")
    if phase in {"metadata", "all"} and not request.confirm_network:
        raise HTTPException(400, "Confirm the Danbooru metadata phase before starting network requests")
    paths = [str(_resolve_tool_folder(request.folder))] if request.folder else _sync_scan_paths()
    if not paths:
        raise HTTPException(400, "Register a media folder first")
    phase_commands = {
        "discover": (_import_discover_command(paths), "Phase 1 · Discover paths"),
        "enrich": (_import_enrich_command(paths), "Phase 2 · Hash and inspect"),
        "metadata": ([
            *_tool_base_command(), "backfill", "--delay", "1.0",
            "--use-indexed-md5", "--database", str(DATA_DB_PATH),
            *(["--limit", str(request.limit)] if request.limit else []),
            *paths,
        ], "Phase 3 · Match Danbooru metadata"),
        "finalize": (_import_finalize_command(paths), "Phase 4 · Finalize index"),
    }
    ordered = ["discover", "enrich", "metadata", "finalize"] if phase == "all" else [phase]
    return _launch_tool(
        "import",
        [phase_commands[item][0] for item in ordered],
        environment=credential_environment(),
        stage_names=[phase_commands[item][1] for item in ordered],
    )


@router.post("/api/import-pipeline/cancel")
def cancel_import():
    return _cancel_tool("import")


@router.get("/api/danbooru/credentials", response_model=DanbooruCredentialStatus)
def get_danbooru_credentials():
    return credentials_status()


@router.put("/api/danbooru/credentials", response_model=DanbooruCredentialStatus)
def update_danbooru_credentials(update: DanbooruCredentialsUpdate):
    try:
        return save_credentials(update.username, update.api_key)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/api/danbooru/credentials", response_model=DanbooruCredentialStatus)
def delete_danbooru_credentials():
    return clear_credentials()


@router.post("/api/danbooru/credentials/check")
def check_danbooru_credentials():
    username, api_key, source = effective_credentials()
    if not username or not api_key:
        raise HTTPException(400, "Save a Danbooru username and API key first")
    token = base64.b64encode(f"{username}:{api_key}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        "https://danbooru.donmai.us/profile.json",
        headers={
            "Authorization": f"Basic {token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            profile = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise HTTPException(400, "Danbooru rejected these credentials") from exc
        raise HTTPException(502, f"Danbooru returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise HTTPException(502, f"Could not reach Danbooru: {exc}") from exc
    return {
        "status": "valid",
        "username": str(profile.get("name") or username),
        "user_id": profile.get("id"),
        "source": source,
    }


def _tool_folders() -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(name: str, path: Path, registered: bool) -> None:
        resolved = path.resolve(strict=False)
        if not resolved.is_dir():
            return
        key = os.path.normcase(str(resolved))
        if key in seen:
            return
        seen.add(key)
        targets.append({
            "name": name,
            "path": str(resolved),
            "registered": registered,
            "exists": resolved.is_dir(),
        })

    for row in registered_folder_rows():
        add(row["name"], Path(row["path"]) if row["path"] else DATA_ROOT / row["name"], True)
    for name in SCAN_FOLDERS:
        add(name, DATA_ROOT / name, False)
    return targets


@router.get("/api/tools/folders", response_model=list[ToolFolderInfo])
def tool_folders():
    return _tool_folders()


def _resolve_tool_folder(folder: str) -> Path:
    path = Path(folder.strip().strip('"')).expanduser()
    if not path.is_absolute():
        path = DATA_ROOT / path
    path = path.resolve(strict=False)
    if not path.is_dir():
        raise HTTPException(400, f"Folder does not exist: {path}")
    for special in (METADATA_DIR, GALLERY_DL_DIR):
        resolved_special = special.resolve(strict=False)
        if path == resolved_special or resolved_special in path.parents:
            raise HTTPException(400, "Metadata and gallery-dl work folders cannot be media targets")
    return path


@router.post("/api/tools/backfill/run", response_model=ToolRunResult)
def run_backfill_tool(request: BackfillToolRequest):
    paths = [_resolve_tool_folder(request.folder)] if request.folder else [Path(path) for path in _sync_scan_paths()]
    if not paths:
        raise HTTPException(400, "Choose a media folder or register library folders first")
    command = [*_tool_base_command(), "backfill", "--delay", "1.0"]
    if request.limit:
        command.extend(["--limit", str(request.limit)])
    command.extend(str(path) for path in paths)
    return _launch_tool(
        "backfill",
        [command],
        environment=credential_environment(),
        stage_names=["Find Danbooru posts by image MD5 and write sidecars"],
    )


@router.get("/api/backups")
def get_backup_configuration():
    return backup_configuration()


@router.get("/api/local-recovery")
def get_local_recovery():
    return local_recovery_status()


@router.post("/api/local-recovery/checkpoint")
def create_recovery_checkpoint():
    try:
        return create_local_recovery_checkpoint("manual")
    except (FileNotFoundError, OSError, RuntimeError, sqlite3.DatabaseError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.put("/api/backups")
def configure_backups(update: BackupConfigurationUpdate):
    try:
        return update_backup_configuration(update.components)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/backups/estimate")
def estimate_backup(request: BackupCreateRequest):
    return backup_estimate(request.components)


@router.post("/api/backups/create")
def create_metadata_backup(request: BackupCreateRequest):
    try:
        with exclusive_tool_operation("backing up"):
            return create_backup_bundle(request.components)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/backups/{backup_name}/inspect")
def inspect_metadata_backup(backup_name: str):
    destination = Path(get_backup_config()["destination"]).expanduser()
    try:
        return inspect_backup_bundle(destination / Path(backup_name).name)
    except (ValueError, FileNotFoundError, KeyError, json.JSONDecodeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/backups/restore")
def restore_metadata_backup(request: BackupRestoreRequest):
    try:
        with exclusive_tool_operation("restoring"):
            return restore_backup_bundle(request.name)
    except (ValueError, FileNotFoundError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


def _valid_thumbnail_keys() -> set[str]:
    with get_data_db() as connection:
        rows = connection.execute("SELECT path, local_md5 FROM files").fetchall()
    return {
        (str(row["local_md5"]).lower() if row["local_md5"] and len(str(row["local_md5"])) == 32 else thumbnail_cache_token(row["path"]))
        for row in rows
    }


@router.get("/api/thumbnails/cache")
def get_thumbnail_cache():
    return thumbnail_cache_status()


@router.post("/api/thumbnails/cache/cleanup")
def cleanup_thumbnails():
    return cleanup_thumbnail_cache(_valid_thumbnail_keys())


@router.post("/api/thumbnails/cache/clear")
def clear_thumbnails():
    removed = clear_thumbnail_cache()
    return {**thumbnail_cache_status(), "removed": removed}


@router.put("/api/thumbnails/cache/limit")
def update_thumbnail_limit(update: ThumbnailCacheLimitUpdate):
    save_config({"thumbnail_cache_limit_gb": update.limit_gb})
    return prune_thumbnail_cache(update.limit_gb * 1024 * 1024 * 1024)


@router.post("/api/tools/{tool_id}/run", response_model=ToolRunResult)
def run_tool(tool_id: str):
    base_command = _tool_base_command()
    scan_paths = _sync_scan_paths()
    sync_all = _sync_command(scan_paths)
    refresh_archive_dir = METADATA_DIR / "sidecar_archive" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    commands: dict[str, list[list[str]]] = {
        "backfill": [[
            *base_command,
            "backfill", "--delay", "1.0", *scan_paths,
        ]],
        "sync": [sync_all],
        "sqlite": [
            [
                *base_command,
                "sqlite", "--output", str(DATA_DB_PATH),
                "--replace", "--no-raw-json", "--commit-every", "5000",
                *_extra_root_args(),
            ],
            sync_all,
        ],
        "clean-sidecars": [[*base_command, "clean-sidecars"]],
        "refresh-tags": [
            [
                *base_command,
                "backfill", "--delay", "1.0", "--overwrite",
                "--archive-replaced-sidecars", "--sidecar-archive-dir", str(refresh_archive_dir),
                *scan_paths,
            ],
            sync_all,
        ],
    }
    tool_commands = commands.get(tool_id)
    if not tool_commands:
        raise HTTPException(404, "Unknown tool")
    stages = {
        "sqlite": ["Rebuild image index", "Sync library"],
        "refresh-tags": ["Update and archive Danbooru sidecars", "Sync updated tags into SQLite"],
    }.get(tool_id)
    return _launch_tool(
        tool_id,
        tool_commands,
        environment=credential_environment(),
        stage_names=stages,
        on_success=(lambda: record_removed_tags_from_archive(refresh_archive_dir)) if tool_id == "refresh-tags" else None,
    )


@router.post("/api/tools/{tool_id}/cancel", response_model=ToolRunResult)
def cancel_tool(tool_id: str):
    if tool_id not in {tool["id"] for tool in TOOL_DEFINITIONS}:
        raise HTTPException(404, "Unknown tool")
    return _cancel_tool(tool_id)


@router.get("/api/tools/{tool_id}/status", response_model=ToolStatusInfo)
def tool_status(tool_id: str):
    task = tool_task_snapshot(tool_id)
    if not task:
        return {"status": "idle", "output": "", "progress": 0, "total": 0}
    return task
