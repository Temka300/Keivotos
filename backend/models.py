from __future__ import annotations

from pydantic import BaseModel, Field


class UserSetting(BaseModel):
    key: str
    value: str


class UserSettingUpdate(BaseModel):
    value: str = Field(max_length=200)


class BackupConfigurationUpdate(BaseModel):
    components: dict[str, bool] = Field(default_factory=dict)


class BackupCreateRequest(BaseModel):
    components: dict[str, bool] | None = None


class BackupRestoreRequest(BaseModel):
    name: str


class ThumbnailCacheLimitUpdate(BaseModel):
    limit_gb: int = Field(ge=1, le=100)
