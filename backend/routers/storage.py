from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool
import config

router = APIRouter()
logger = logging.getLogger("keivotos.diagnostics")


@router.get("/api/storage")
def storage_configuration():
    return config.public_storage_config()


class DiagnosticsPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verbose_logging: StrictBool
    show_experimental_modules: StrictBool


@router.get("/api/diagnostics", response_model=DiagnosticsPreferences)
def diagnostics_preferences():
    return config.get_diagnostics_preferences()


@router.put("/api/diagnostics", response_model=DiagnosticsPreferences)
def update_diagnostics(preferences: DiagnosticsPreferences):
    config.save_config(preferences.model_dump())
    logger.info("Diagnostics preferences updated: verbose logging=%s, experimental visibility=%s",
                preferences.verbose_logging, preferences.show_experimental_modules)
    return config.get_diagnostics_preferences()


@router.post("/api/diagnostics/open/{target}")
def open_diagnostics(target: Literal["data", "logs", "runtime", "access", "backups"]):
    # Fixed destinations only: never accept a caller-supplied filesystem path.
    paths = {"data": config.SUITE_HOME, "logs": config.LOG_DIR,
             "runtime": config.RUNTIME_LOG_FILE, "access": config.ACCESS_LOG_FILE}
    if target == "backups":
        try:
            path = config.validate_backup_destination(config.get_backup_config()["destination"])
            path.mkdir(parents=True, exist_ok=True)
        except (OSError, ValueError) as exc:
            logger.exception("Could not open backup location")
            raise HTTPException(503, "Could not access the backup location. Check Logs for details.") from exc
    else:
        path = paths[target]
    if not path.exists():
        raise HTTPException(404, "This location is not available yet")
    if target in {"runtime", "access"} and not path.resolve().is_relative_to(config.LOG_DIR.resolve()):
        raise HTTPException(409, "The log file points outside the logs folder")
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        logger.exception("Could not open diagnostics target %s", target)
        raise HTTPException(503, "Could not open this location with your desktop application") from exc
    logger.info("Opened diagnostics target %s", target)
    return {"status": "opened"}
