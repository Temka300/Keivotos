from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from modules.danbooru.automation import automation_status, set_automation_enabled
from config import DATA_DB_PATH, DATA_ROOT, GALLERY_DL_DIR, METADATA_DIR, SCAN_FOLDERS
from modules.danbooru.credentials import clear_credentials, credential_environment, credentials_status, effective_credentials, save_credentials
from database import get_data_db
from modules.danbooru.client import USER_AGENT
from modules.danbooru.folder_registry import registered_folder_rows
from modules.danbooru.tools import _cancel_tool, _extra_root_args, _import_discover_command, _import_enrich_command, _import_finalize_command, _launch_tool, _sync_command, _sync_scan_paths, _tool_base_command, tool_task_snapshot
from modules.danbooru.models import AutomationStatus, AutomationUpdate, ImportRunRequest, ToolStatusInfo
from modules.danbooru.models import BackfillToolRequest, DanbooruCredentialsUpdate, DanbooruCredentialStatus, ToolFolderInfo, ToolInfo, ToolRunResult
from modules.danbooru.tag_history import record_removed_tags_from_archive

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
    try:
        return credentials_status()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/api/danbooru/credentials", response_model=DanbooruCredentialStatus)
def update_danbooru_credentials(update: DanbooruCredentialsUpdate):
    try:
        return save_credentials(update.username, update.api_key)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/api/danbooru/credentials", response_model=DanbooruCredentialStatus)
def delete_danbooru_credentials():
    try:
        return clear_credentials()
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


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
