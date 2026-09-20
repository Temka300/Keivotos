from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class UserSetting(BaseModel):
    key: str
    value: str


class UserSettingUpdate(BaseModel):
    value: str = Field(max_length=200)


class BackupOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool = False
    location: Literal["default", "custom"] = "default"
    custom_location: str = Field(default="", max_length=4096)
    retention: int = Field(default=3, ge=1, le=5, strict=True)
    frequency_minutes: Literal[15, 30, 45, 60] = 60
    remembered_components: dict[str, StrictBool] = Field(default_factory=dict)


class BackupConfigurationUpdate(BaseModel):
    components: dict[str, bool] = Field(default_factory=dict)
    options: BackupOptions | None = None


class BackupCreateRequest(BaseModel):
    components: dict[str, bool] | None = None


class BackupRestoreRequest(BaseModel):
    name: str


class ThumbnailCacheLimitUpdate(BaseModel):
    limit_gb: int = Field(ge=1, le=100)
