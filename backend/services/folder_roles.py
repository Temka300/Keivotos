"""Suite-level orchestration for the shared folder registry and module roles."""
from __future__ import annotations

import os
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import suite_modules
from config import FILES_DB_PATH, MODULE_REGISTRY, SUITE_HOME
from database import get_user_db
from files_base import index, sources
from maintenance import module_operation


class FolderRegistryError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class FolderChange:
    source_id: str | None
    path: str | None
    display_name: str
    role: str
    visible: bool = True
    forget: bool = False


@contextmanager
def _folder_work(source_ids: list[str], roles: tuple[str, ...] | list[str] = ()):
    with get_user_db() as connection:
        sources.ensure_sources_schema(connection)
        owners = {sources.canonical_role(role) for role in roles}
        for source_id in source_ids:
            source = sources.get_source(connection, source_id)
            if source is not None:
                owners.add(sources.canonical_role(source.role))
    guard = module_operation() if owners - {"files"} else nullcontext()
    try:
        with guard:
            yield
    except RuntimeError as exc:
        if isinstance(exc, FolderRegistryError):
            raise
        from lifecycle import ModuleStartError
        raise FolderRegistryError(503 if isinstance(exc, ModuleStartError) else 409, str(exc)) from exc


def _require_owner(role: str):
    canonical = sources.canonical_role(role)
    suite_modules.require_enabled(canonical)
    return MODULE_REGISTRY.require(canonical)


def _normalized_path(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve(strict=False)))


def _validate_role(role: str, enabled: set[str]) -> str:
    canonical = sources.canonical_role(role)
    descriptor = MODULE_REGISTRY.get(canonical)
    if descriptor is None:
        raise FolderRegistryError(400, f"Unknown folder role: {role}")
    if descriptor.disableable and descriptor.slug not in enabled:
        raise FolderRegistryError(409, f"Enable {descriptor.name} before assigning folders to it")
    suite_modules.require_enabled(descriptor.slug)
    return descriptor.slug


def _validate_changes(changes: list[FolderChange]) -> tuple[list[tuple[FolderChange, sources.Source, str]], list[tuple[FolderChange, Path, str]]]:
    with get_user_db() as connection:
        sources.ensure_sources_schema(connection)
        existing = {source.source_id: source for source in sources.list_sources(connection)}
        suite_modules.ensure_schema(connection)
        enabled = suite_modules.enabled_ids(connection)

    existing_changes: list[tuple[FolderChange, sources.Source, str]] = []
    additions: list[tuple[FolderChange, Path, str]] = []
    seen_ids: set[str] = set()
    seen_paths = {_normalized_path(source.path) for source in existing.values()}
    for change in changes:
        name = change.display_name.strip()
        if not name:
            raise FolderRegistryError(400, "Folder display names cannot be blank")
        if change.source_id:
            if change.source_id in seen_ids:
                raise FolderRegistryError(400, "A folder can appear only once in a batch")
            seen_ids.add(change.source_id)
            source = existing.get(change.source_id)
            if source is None:
                raise FolderRegistryError(404, f"Unknown folder source: {change.source_id}")
            requested_role = sources.canonical_role(change.role)
            current_role = sources.canonical_role(source.role)
            # Shared presentation remains editable while the owner is disabled.
            # Releasing or forgetting invokes that owner and requires enablement.
            if change.forget or requested_role != current_role:
                _require_owner(current_role)
            role = requested_role if requested_role == current_role else _validate_role(requested_role, enabled)
            if change.path and _normalized_path(change.path) != _normalized_path(source.path):
                raise FolderRegistryError(400, "A registered folder path cannot be changed by rename")
            existing_changes.append((change, source, role))
            continue
        if change.forget:
            raise FolderRegistryError(400, "A new folder cannot be marked forgotten")
        if not change.path:
            raise FolderRegistryError(400, "New folders require an absolute path")
        role = _validate_role(change.role, enabled)
        reason = sources.unsafe_source_reason(change.path, [SUITE_HOME])
        if reason is not None:
            raise FolderRegistryError(400, reason)
        resolved = Path(change.path).expanduser().resolve(strict=False)
        normalized = _normalized_path(resolved)
        if normalized in seen_paths:
            raise FolderRegistryError(409, f"Folder is already registered: {resolved}")
        seen_paths.add(normalized)
        additions.append((change, resolved, role))
    return existing_changes, additions


def _scan_registered_source(
    index_connection,
    source: sources.Source,
    all_sources: list[sources.Source],
) -> dict[str, int]:
    excluded = [
        Path(candidate.path)
        for candidate in sources.descendant_sources(source, all_sources)
    ]
    return index.scan_source(
        index_connection,
        source.source_id,
        Path(source.path),
        excluded_roots=excluded,
    )


def apply_changes(changes: list[FolderChange]) -> dict[str, Any]:
    with _folder_work([c.source_id for c in changes if c.source_id], [c.role for c in changes]):
        return _apply_changes(changes)


def _apply_changes(changes: list[FolderChange]) -> dict[str, Any]:
    """Validate the full draft, then apply it when the user presses Save."""
    existing_changes, additions = _validate_changes(changes)
    adopted: list[str] = []
    released: list[str] = []
    forgotten: list[str] = []
    forgotten_paths: list[str] = []
    scans: list[dict[str, Any]] = []

    # Presentation edits are short user-DB writes and are applied together.
    with get_user_db() as connection:
        sources.ensure_sources_schema(connection)
        for change, source, _ in existing_changes:
            if change.forget:
                continue
            sources.update_source(
                connection,
                source.source_id,
                display_name=change.display_name,
                visible=change.visible,
                commit=False,
            )
        connection.commit()

    for change, source, target_role in existing_changes:
        current_role = sources.canonical_role(source.role)
        current_descriptor = MODULE_REGISTRY.get(current_role)
        if change.forget:
            forgotten_paths.append(source.path)
            preview = forget_preview(source.source_id)
            if not current_descriptor.is_base:
                current_descriptor.release(source.source_id, True)
            else:
                with get_user_db() as connection:
                    sources.ensure_sources_schema(connection)
                    sources.remove_source(connection, source.source_id)
            with index.open_index(FILES_DB_PATH) as index_connection:
                base_removed = index.drop_source(index_connection, source.source_id)
            forgotten.append(source.source_id)
            scans.append({**preview, "base_files_unindexed": base_removed})
            continue

        target_descriptor = MODULE_REGISTRY.get(target_role)
        if current_role != target_role:
            if not current_descriptor.is_base:
                current_descriptor.release(source.source_id, False)
                released.append(source.source_id)
            if not target_descriptor.is_base:
                target_descriptor.adopt(source.source_id)
                adopted.append(source.source_id)
            else:
                with get_user_db() as connection:
                    sources.ensure_sources_schema(connection)
                    sources.update_source(connection, source.source_id, role=target_descriptor.slug)
        else:
            if current_descriptor is None:
                continue
            try:
                suite_modules.require_enabled(current_role)
            except RuntimeError:
                continue  # Shared presentation remains editable for unavailable owners.
            current_descriptor.update_folder(source.source_id)

    for change, path, target_role in additions:
        with get_user_db() as connection:
            sources.ensure_sources_schema(connection)
            source = sources.register_source(connection, path, change.display_name, role="files")
            sources.update_source(connection, source.source_id, visible=change.visible)
            current_sources = sources.list_sources(connection)
        with index.open_index(FILES_DB_PATH) as index_connection:
            scan = _scan_registered_source(index_connection, source, current_sources)
        scans.append({"source_id": source.source_id, **scan})
        descriptor = MODULE_REGISTRY.require(target_role)
        if not descriptor.is_base:
            descriptor.adopt(source.source_id)
            adopted.append(source.source_id)

    with get_user_db() as connection:
        sources.ensure_sources_schema(connection)
        current = sources.list_sources(connection)
    if forgotten_paths:
        rescanned: set[str] = set()
        with index.open_index(FILES_DB_PATH) as index_connection:
            for path in forgotten_paths:
                ancestor = sources.nearest_ancestor_source(path, current)
                if ancestor is None or ancestor.source_id in rescanned:
                    continue
                _scan_registered_source(index_connection, ancestor, current)
                rescanned.add(ancestor.source_id)
    return {
        "sources": current,
        "adopted": adopted,
        "released": released,
        "forgotten": forgotten,
        "operations": scans,
    }


def rescan(source_id: str) -> dict[str, Any]:
    with _folder_work([source_id]):
        return _rescan(source_id)


def _rescan(source_id: str) -> dict[str, Any]:
    """Re-index one folder through its owning module.

    The base always refreshes its own filesystem index (browse/thumbnails); a
    non-base owner then runs its richer rescan (e.g. the Danbooru library sync).
    The suite only dispatches — each module decides what "rescan" means for its
    role — which keeps the base module-agnostic.
    """
    with get_user_db() as connection:
        sources.ensure_sources_schema(connection)
        source = sources.get_source(connection, source_id)
        all_sources = sources.list_sources(connection)
    if source is None:
        raise FolderRegistryError(404, "Unknown folder source")
    descriptor = _require_owner(source.role)
    with index.open_index(FILES_DB_PATH) as index_connection:
        base = _scan_registered_source(index_connection, source, all_sources)
    module = {} if descriptor.is_base else descriptor.rescan(source_id)
    return {"source_id": source_id, "base": base, "module": module}


def relocate(source_id: str, new_path: str) -> dict[str, Any]:
    with _folder_work([source_id]):
        return _relocate(source_id, new_path)


def _relocate(source_id: str, new_path: str) -> dict[str, Any]:
    """Point a moved folder at its new location through its owning module.

    Files folders take their identity from their path, so relocating one is just
    removing it and adding the new path — the caller should do that instead. A
    module folder keeps a stable identity: its module rewrites its own index and
    re-publishes the shared source (a new path-derived id), and we then refresh
    the base index at the new location.
    """
    with get_user_db() as connection:
        sources.ensure_sources_schema(connection)
        source = sources.get_source(connection, source_id)
    if source is None:
        raise FolderRegistryError(404, "Unknown folder source")
    descriptor = _require_owner(source.role)
    if descriptor.is_base:
        raise FolderRegistryError(
            400,
            "Files folders are identified by their path — remove this one and add it at the new location.",
        )
    try:
        result = descriptor.relocate(source_id, new_path)
    except ValueError as exc:
        raise FolderRegistryError(400, str(exc)) from exc
    with get_user_db() as connection:
        sources.ensure_sources_schema(connection)
        descriptor.publish(connection)
        moved = sources.get_source(connection, sources.deterministic_source_id(new_path))
        all_sources = sources.list_sources(connection)
    if moved is not None:
        with index.open_index(FILES_DB_PATH) as index_connection:
            index.drop_source(index_connection, source_id)
            _scan_registered_source(index_connection, moved, all_sources)
    return {
        "source_id": moved.source_id if moved is not None else source_id,
        "files_updated": int(result.get("files_updated", 0)),
    }


def forget_preview(source_id: str) -> dict[str, Any]:
    with _folder_work([source_id]):
        return _forget_preview(source_id)


def _forget_preview(source_id: str) -> dict[str, Any]:
    with get_user_db() as connection:
        sources.ensure_sources_schema(connection)
        source = sources.get_source(connection, source_id)
    if source is None:
        raise FolderRegistryError(404, "Unknown folder source")
    descriptor = _require_owner(source.role)
    with index.open_index(FILES_DB_PATH) as index_connection:
        base_files = index.source_entry_count(index_connection, source_id)
    module = descriptor.folder_preview(source_id)
    return {
        "source_id": source_id,
        "display_name": source.display_name,
        "base_files": base_files,
        "module_files": int(module.get("module_files", 0)),
        "sidecars_preserved": int(module.get("sidecars_preserved", 0)),
    }
