from __future__ import annotations

import json
import zipfile
from pathlib import Path
from fastapi import APIRouter, HTTPException
from backup_bundle import backup_configuration, backup_estimate, create_backup_bundle, inspect_backup_bundle, restore_backup_bundle, update_backup_configuration
from config import get_backup_config
# Preserve the existing tool exclusion window until shared locking is extracted.
from modules.danbooru.tools import exclusive_tool_operation
from models import BackupConfigurationUpdate, BackupCreateRequest, BackupRestoreRequest

router = APIRouter()


@router.get("/api/backups")
def get_backup_configuration():
    return backup_configuration()


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
