"""Protect module startup/shutdown before separating the legacy initializers.

Real descriptor dispatch and asyncio tasks; all disk/network startup work is
replaced. These tests cover existing guarantees, not the planned live toggle,
physical removal, or failure-state UI.
"""
from __future__ import annotations

import asyncio
from contextlib import ExitStack, nullcontext
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import lifecycle  # noqa: E402
from module_descriptor import ModuleDescriptor  # noqa: E402
from module_registry import ModuleRegistry  # noqa: E402


def descriptor(slug: str, *, base: bool = False, **hooks) -> ModuleDescriptor:
    return ModuleDescriptor(
        slug=slug, name=slug, home=Path("unused") / slug,
        database=Path("unused") / slug / "index.sqlite", credentials=None,
        api_prefix=f"/api/{slug}", log_prefix=slug, user_agent="test",
        disableable=not base, is_base=base, **hooks,
    )


class ModuleLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        # Never run migrations, create a default library, or touch a real DB.
        for name, result in (
            ("promote_user_database", {}),
            ("promote_legacy_module_backups", {}),
            ("migrate_legacy_default_metadata", {"migrated": False}),
            ("migrate_legacy_thumbnail_cache", {}),
            ("init_data_db", None),
            ("init_user_db", None),
            ("install_first_run_default_library", None),
        ):
            self.patches.enter_context(patch.object(lifecycle, name, return_value=result))
        self.connection = object()
        self.patches.enter_context(patch.object(
            lifecycle, "get_user_db", side_effect=lambda: nullcontext(self.connection),
        ))
        self.checkpoint = self.patches.enter_context(patch.object(
            lifecycle, "create_local_recovery_checkpoint", return_value={"message": "fixture"},
        ))

    def registry(self, *modules: ModuleDescriptor, enabled: set[str]) -> None:
        self.patches.enter_context(patch.object(lifecycle, "MODULE_REGISTRY", ModuleRegistry(modules)))
        self.patches.enter_context(patch.object(lifecycle, "_active_module_slugs", return_value=enabled))

    async def test_disabled_module_never_publishes_starts_or_constructs_tasks(self) -> None:
        publish, startup, tasks = Mock(), Mock(), Mock()
        base_startup = Mock()
        self.registry(
            descriptor("files", base=True, startup_hook=base_startup),
            descriptor("optional", publish_hook=publish, startup_hook=startup,
                       background_tasks_hook=tasks),
            enabled=set(),
        )
        async with lifecycle.lifespan(None):
            base_startup.assert_called_once_with()
            publish.assert_not_called()
            startup.assert_not_called()
            tasks.assert_not_called()

    async def test_enabled_module_publishes_before_start_and_worker_is_stopped(self) -> None:
        events = []
        started, stopped = asyncio.Event(), asyncio.Event()

        def publish(connection):
            self.assertIs(connection, self.connection)
            events.append("publish")

        async def worker():
            events.append("worker")
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        def tasks():
            events.append("tasks")
            return [("fixture-module-worker", worker())]

        self.registry(
            descriptor("files", base=True),
            descriptor("optional", publish_hook=publish,
                       startup_hook=lambda: events.append("startup"), background_tasks_hook=tasks),
            enabled={"optional"},
        )
        async with lifecycle.lifespan(None):
            await asyncio.wait_for(started.wait(), timeout=2)
            self.assertEqual(events, ["publish", "startup", "tasks", "worker"])
            self.assertFalse(stopped.is_set())
        self.assertTrue(stopped.is_set(), "Shutdown must await worker cleanup")
        self.assertFalse(any(t.get_name() == "fixture-module-worker" for t in asyncio.all_tasks()))

    async def test_hook_failure_does_not_prevent_another_module_starting(self) -> None:
        for hook in ("publish_hook", "startup_hook", "background_tasks_hook"):
            with self.subTest(hook=hook), ExitStack() as iteration:
                healthy = Mock()
                iteration.enter_context(patch.object(lifecycle, "MODULE_REGISTRY", ModuleRegistry((
                    descriptor("files", base=True),
                    descriptor("broken", **{hook: Mock(side_effect=RuntimeError("fixture failure"))}),
                    descriptor("healthy", startup_hook=healthy),
                ))))
                iteration.enter_context(patch.object(
                    lifecycle, "_active_module_slugs", return_value={"broken", "healthy"},
                ))
                with self.assertLogs("lifecycle", level="WARNING") as logs:
                    async with lifecycle.lifespan(None):
                        healthy.assert_called_once_with()
                self.assertTrue(any("broken" in message and "fixture failure" in message
                                    for message in logs.output))

    async def test_recovery_runs_with_no_optional_module_enabled(self) -> None:
        self.registry(descriptor("files", base=True), enabled=set())
        async with lifecycle.lifespan(None):
            recovery = next(t for t in asyncio.all_tasks() if t.get_name() == "suite-recovery-checkpoint")
            await asyncio.wait_for(asyncio.shield(recovery), timeout=2)
        self.checkpoint.assert_called_once_with("startup")

    async def test_recovery_failure_does_not_abort_suite_lifetime(self) -> None:
        self.checkpoint.side_effect = RuntimeError("fixture checkpoint failure")
        self.registry(descriptor("files", base=True), enabled=set())
        with self.assertLogs("lifecycle", level="WARNING") as logs:
            async with lifecycle.lifespan(None):
                recovery = next(t for t in asyncio.all_tasks() if t.get_name() == "suite-recovery-checkpoint")
                await asyncio.wait_for(asyncio.shield(recovery), timeout=2)
        self.assertTrue(any("fixture checkpoint failure" in message for message in logs.output))


if __name__ == "__main__":
    unittest.main()
