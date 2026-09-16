from __future__ import annotations

import sqlite3
from fastapi import APIRouter, HTTPException
from local_recovery import create_local_recovery_checkpoint, local_recovery_status

router = APIRouter()


@router.get("/api/local-recovery")
def get_local_recovery():
    return local_recovery_status()


@router.post("/api/local-recovery/checkpoint")
def create_recovery_checkpoint():
    try:
        return create_local_recovery_checkpoint("manual")
    except (FileNotFoundError, OSError, RuntimeError, sqlite3.DatabaseError) as exc:
        raise HTTPException(409, str(exc)) from exc
