"""Typed boundary between the Keivotos suite shell and its modules."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ContextManager


PublishHook = Callable[[sqlite3.Connection], None]
AdoptHook = Callable[[str], dict[str, Any]]
ReleaseHook = Callable[[str, bool], dict[str, Any]]
FolderPreviewHook = Callable[[str], dict[str, Any]]
FolderUpdateHook = Callable[[str], None]
RescanHook = Callable[[str], dict[str, Any]]
RelocateHook = Callable[[str, str], dict[str, Any]]
# Returns the APIRouters this surface contributes. Typed loosely so this
# boundary module need not import FastAPI; the shell mounts whatever comes back.
RouterProvider = Callable[[], "list[Any]"]
# Synchronous once-at-startup work for an active module (e.g. a schema/migration).
StartupHook = Callable[[], None]
IndexInitializer = Callable[[Path, Callable[[], ContextManager[sqlite3.Connection]]], None]
# Returns ``(name, coroutine)`` pairs the suite lifespan runs as background tasks
# for the module's lifetime. Typed loosely to keep asyncio out of this boundary.
BackgroundTasksHook = Callable[[], "list[Any]"]


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
    rescan_hook: RescanHook | None = None
    relocate_hook: RelocateHook | None = None
    router_provider: RouterProvider | None = None
    startup_hook: StartupHook | None = None
    background_tasks_hook: BackgroundTasksHook | None = None

    index_initializer: IndexInitializer | None = None
    user_schema_provider: Callable[[], str] | None = None
    user_migrator: Callable[[sqlite3.Connection, Path, Path], None] | None = None

    def run_startup(self) -> None:
        """Synchronous once-at-startup work, run only when the module is active."""
        if self.startup_hook is not None:
            self.startup_hook()

    def background_tasks(self) -> "list[Any]":
        """``(name, coroutine)`` pairs to run for the module's lifetime.

        Resolved only when the module is active, so a disabled module never
        constructs its coroutines. An empty list means no background work.
        """
        if self.background_tasks_hook is None:
            return []
        return list(self.background_tasks_hook())

    def routers(self) -> "list[Any]":
        """The APIRouters this surface contributes, resolved lazily at compose time.

        Returning them from a provider (rather than importing routers when the
        registry is built) keeps descriptor construction free of route imports,
        so ``config`` can build the registry without pulling in a module's HTTP
        layer. A surface with no HTTP routes returns an empty list.
        """
        if self.router_provider is None:
            return []
        return list(self.router_provider())

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

    def rescan(self, source_id: str) -> dict[str, Any]:
        """Module-specific re-index for one folder (e.g. a library sync).

        The base's own filesystem index is refreshed by the suite regardless; a
        module that has nothing extra to do simply reports no module work.
        """
        if self.rescan_hook is None:
            return {}
        return self.rescan_hook(source_id)

    def relocate(self, source_id: str, new_path: str) -> dict[str, Any]:
        """Point a moved folder at ``new_path``, preserving the module's identity."""
        if self.relocate_hook is None:
            raise ValueError(f"{self.name} folders cannot be relocated")
        return self.relocate_hook(source_id, new_path)
