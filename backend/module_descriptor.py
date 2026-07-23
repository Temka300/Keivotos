"""Typed boundary between the Keivotos suite shell and its modules."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PublishHook = Callable[[sqlite3.Connection], None]
AdoptHook = Callable[[str], dict[str, Any]]
ReleaseHook = Callable[[str, bool], dict[str, Any]]
FolderPreviewHook = Callable[[str], dict[str, Any]]
FolderUpdateHook = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class ModuleDescriptor:
    """Static identity and suite integration points for one registered surface.

    Paths are resolved when the registry is built for a particular suite home.
    The shell consumes descriptors; compatibility modules may continue exposing
    their historical constants while they are migrated incrementally.
    """

    slug: str
    name: str
    home: Path
    database: Path
    credentials: Path | None
    api_prefix: str
    log_prefix: str
    user_agent: str
    disableable: bool
    is_base: bool
    publish_hook: PublishHook | None = None
    adopt_hook: AdoptHook | None = None
    release_hook: ReleaseHook | None = None
    folder_preview_hook: FolderPreviewHook | None = None
    folder_update_hook: FolderUpdateHook | None = None

    def publish(self, user_connection: sqlite3.Connection) -> None:
        if self.publish_hook is not None:
            self.publish_hook(user_connection)

    def adopt(self, source_id: str) -> dict[str, Any]:
        if self.adopt_hook is None:
            raise ValueError(f"{self.name} does not accept folder assignments")
        return self.adopt_hook(source_id)

    def release(self, source_id: str, forget: bool = False) -> dict[str, Any]:
        if self.release_hook is None:
            raise ValueError(f"{self.name} does not own folder assignments")
        return self.release_hook(source_id, forget)

    def folder_preview(self, source_id: str) -> dict[str, Any]:
        if self.folder_preview_hook is None:
            return {"module_files": 0, "sidecars_preserved": 0}
        return self.folder_preview_hook(source_id)

    def update_folder(self, source_id: str) -> None:
        if self.folder_update_hook is not None:
            self.folder_update_hook(source_id)
