from __future__ import annotations

from fastapi import APIRouter, HTTPException
from local_recovery import local_recovery_status

router = APIRouter()


@router.get("/api/local-recovery")
def get_local_recovery():
    return local_recovery_status()


@router.post("/api/local-recovery/checkpoint")
def create_recovery_checkpoint():
    raise HTTPException(410, "Standalone checkpoints have been retired. Use Settings > Backup.")
