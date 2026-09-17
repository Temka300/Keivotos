"""HTTP surface for suite-level module management: ``/api/suite/*`` (V1.1.0).

Lists the modules the suite knows about with their enabled state, and
enables/disables them. Isolated from ``core``; uses only the shared user-DB
accessor and the standalone ``suite_modules`` registry.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

import suite_modules
from database import get_user_db, init_data_db, init_user_db
from services import folder_roles
from maintenance import exclusive_tool_operation

router = APIRouter()


class SuiteModule(BaseModel):
    id: str
    slug: str
    name: str
    enabled: bool
    disableable: bool
    is_base: bool
    api_prefix: str


class FolderChangePayload(BaseModel):
    source_id: str | None = None
    path: str | None = None
    display_name: str
    role: str
    visible: bool = True
    forget: bool = False


class FolderBatchPayload(BaseModel):
    folders: list[FolderChangePayload]


class ManagedFolder(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    path: str
    display_name: str
    role: str
    visible: bool
    added_at: str | None = None


class FolderBatchResult(BaseModel):
    sources: list[ManagedFolder]
    adopted: list[str]
    released: list[str]
    forgotten: list[str]
    operations: list[dict]


class FolderForgetPreview(BaseModel):
    source_id: str
    display_name: str
    base_files: int
    module_files: int
    sidecars_preserved: int


class FolderRescanResult(BaseModel):
    source_id: str
    base: dict
    module: dict


class FolderRelocatePayload(BaseModel):
    path: str


class FolderRelocateResult(BaseModel):
    source_id: str
    files_updated: int = 0


@router.get("/api/suite/modules", response_model=list[SuiteModule])
def list_modules() -> list[SuiteModule]:
    with get_user_db() as user_conn:
        suite_modules.ensure_schema(user_conn)
        enabled = suite_modules.enabled_ids(user_conn)
    return [
        SuiteModule(
            id=descriptor.slug,
            slug=descriptor.slug,
            name=descriptor.name,
            enabled=descriptor.is_base or descriptor.slug in enabled,
            disableable=descriptor.disableable,
            is_base=descriptor.is_base,
            api_prefix=descriptor.api_prefix,
        )
        for descriptor in suite_modules.descriptors()
    ]


def _set_enabled(module_id: str, enabled: bool) -> SuiteModule:
    if not suite_modules.is_known(module_id):
        raise HTTPException(status_code=404, detail="Unknown module")
    descriptor = suite_modules.MODULE_REGISTRY.require(module_id)
    if not descriptor.disableable and not enabled:
        raise HTTPException(status_code=409, detail=f"{descriptor.name} cannot be disabled")
    with get_user_db() as user_conn:
        suite_modules.ensure_schema(user_conn)
        already_enabled = module_id in suite_modules.enabled_ids(user_conn)
    if enabled and descriptor.disableable and not already_enabled:
        # Prepare persisted storage before exposing an enabled module. Worker
        # lifecycle coordination is separate from this initialization boundary.
        try:
            with exclusive_tool_operation("enabling module"):
                if descriptor.storage_migration_hook is not None:
                    descriptor.storage_migration_hook()
                init_data_db({module_id})
                init_user_db({module_id})
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    with get_user_db() as user_conn:
        suite_modules.ensure_schema(user_conn)
        try:
            suite_modules.set_enabled(user_conn, module_id, enabled)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SuiteModule(
        id=descriptor.slug,
        slug=descriptor.slug,
        name=descriptor.name,
        enabled=descriptor.is_base or enabled,
        disableable=descriptor.disableable,
        is_base=descriptor.is_base,
        api_prefix=descriptor.api_prefix,
    )


@router.post("/api/suite/modules/{module_id}/enable", response_model=SuiteModule)
def enable_module(module_id: str) -> SuiteModule:
    return _set_enabled(module_id, True)


@router.post("/api/suite/modules/{module_id}/disable", response_model=SuiteModule)
def disable_module(module_id: str) -> SuiteModule:
    return _set_enabled(module_id, False)


@router.post("/api/suite/folders/apply", response_model=FolderBatchResult)
def apply_folder_changes(payload: FolderBatchPayload) -> FolderBatchResult:
    changes = [folder_roles.FolderChange(**change.model_dump()) for change in payload.folders]
    try:
        return FolderBatchResult(**folder_roles.apply_changes(changes))
    except folder_roles.FolderRegistryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.get(
    "/api/suite/folders/{source_id}/forget-preview",
    response_model=FolderForgetPreview,
)
def preview_folder_forget(source_id: str) -> FolderForgetPreview:
    try:
        return FolderForgetPreview(**folder_roles.forget_preview(source_id))
    except folder_roles.FolderRegistryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/api/suite/folders/{source_id}/rescan", response_model=FolderRescanResult)
def rescan_folder_source(source_id: str) -> FolderRescanResult:
    """Re-index one registered folder through the module that owns it."""
    try:
        return FolderRescanResult(**folder_roles.rescan(source_id))
    except folder_roles.FolderRegistryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.put("/api/suite/folders/{source_id}/path", response_model=FolderRelocateResult)
def relocate_folder_source(source_id: str, payload: FolderRelocatePayload) -> FolderRelocateResult:
    """Point a moved folder at a new path through the module that owns it."""
    try:
        return FolderRelocateResult(**folder_roles.relocate(source_id, payload.path))
    except folder_roles.FolderRegistryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
