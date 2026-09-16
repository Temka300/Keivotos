from __future__ import annotations

from fastapi import APIRouter, HTTPException
from database import get_user_db
from models import UserSetting, UserSettingUpdate
from product import SUITE_NAME

router = APIRouter()
PROFILE_NAME_KEY = "profile_name"
SUPPORTED_USER_SETTING_KEYS = {PROFILE_NAME_KEY}


def _user_setting_value(key: str, value: str) -> str:
    if key != PROFILE_NAME_KEY:
        raise HTTPException(404, "User setting not found")
    normalized = value.strip()[:40]
    return normalized or SUITE_NAME


@router.get("/api/user-settings/{key}", response_model=UserSetting)
def get_user_setting(key: str):
    if key not in SUPPORTED_USER_SETTING_KEYS:
        raise HTTPException(404, "User setting not found")
    with get_user_db() as conn:
        row = conn.execute("SELECT value FROM user_settings WHERE key=?", (key,)).fetchone()
    value = _user_setting_value(key, row["value"] if row else SUITE_NAME)
    return UserSetting(key=key, value=value)


@router.put("/api/user-settings/{key}", response_model=UserSetting)
def put_user_setting(key: str, update: UserSettingUpdate):
    value = _user_setting_value(key, update.value)
    with get_user_db() as conn:
        conn.execute(
            """INSERT INTO user_settings(key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value,
                   updated_at=excluded.updated_at""",
            (key, value),
        )
        conn.commit()
    return UserSetting(key=key, value=value)


