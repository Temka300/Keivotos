from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from fastapi import APIRouter, HTTPException
from backup_bundle import backup_configuration, backup_estimate, create_backup_bundle, inspect_backup_bundle, restore_backup_bundle, update_backup_configuration
from config import get_backup_config
from maintenance import exclusive_tool_operation
from models import BackupConfigurationUpdate, BackupCreateRequest, BackupRestoreRequest

router = APIRouter()
logger = logging.getLogger("keivotos.backups")


@router.get("/api/backups")
def get_backup_configuration():
    return backup_configuration()


@router.get("/api/backups/automatic-status")
def get_automatic_backup_status():
    from automatic_backups import automatic_backup_status
    return automatic_backup_status()


@router.put("/api/backups")
def configure_backups(update: BackupConfigurationUpdate):
    try:
        with exclusive_tool_operation("configuring backups", wait=False):
            return update_backup_configuration(update.components, update.options.model_dump() if update.options else None)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/backups/estimate")
def estimate_backup(request: BackupCreateRequest):
    return backup_estimate(request.components)


@router.post("/api/backups/create")
def create_metadata_backup(request: BackupCreateRequest):
    try:
        with exclusive_tool_operation("backing up", wait=False):
            return create_backup_bundle(request.components)
    except OSError as exc:
        logger.exception("Backup could not access its files")
        raise HTTPException(400, "Could not write the backup. Check the location and Logs.") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/api/backups/{backup_name}/inspect")
def inspect_metadata_backup(backup_name: str):
    destination = Path(get_backup_config()["destination"]).expanduser().resolve()
    try:
        source = (destination / Path(backup_name).name).resolve()
        if source.parent != destination:
            raise ValueError("Backup must be inside the configured backup location")
        return inspect_backup_bundle(source)
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
