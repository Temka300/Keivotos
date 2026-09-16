from __future__ import annotations

from fastapi import APIRouter
from config import public_storage_config

router = APIRouter()


@router.get("/api/storage")
def storage_configuration():
    return public_storage_config()
