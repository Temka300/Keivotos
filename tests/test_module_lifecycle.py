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
            __import__("local_recovery"), "create_local_recovery_checkpoint", side_effect=AssertionError("retired checkpoint called"),
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

    async def test_storage_failure_keeps_files_and_other_modules_running(self) -> None:
        files, healthy = Mock(), Mock()
        self.registry(
            descriptor("files", base=True, startup_hook=files),
            descriptor("broken", storage_migration_hook=Mock(side_effect=OSError("fixture storage"))),
            descriptor("healthy", startup_hook=healthy),
            enabled={"broken", "healthy"},
        )
        with self.assertLogs("lifecycle", level="ERROR"):
            async with lifecycle.lifespan(None):
                files.assert_called_once()
                healthy.assert_called_once()
                self.assertEqual(lifecycle.module_runtime.status("broken")["state"], "failed")
                self.assertEqual(lifecycle.module_runtime.status("healthy")["state"], "running")
                self.assertNotIn("broken", lifecycle.module_runtime.tasks)

    async def test_unreadable_enablement_does_not_activate_optional_module(self) -> None:
        optional = Mock()
        self.registry(descriptor("files", base=True), descriptor("optional", startup_hook=optional), enabled=None)
        with self.assertLogs("lifecycle", level="ERROR"):
            async with lifecycle.lifespan(None):
                optional.assert_not_called()
                self.assertEqual(lifecycle.module_runtime.status("files")["state"], "running")
                self.assertEqual(lifecycle.module_runtime.status("optional")["state"], "failed")

    async def test_startup_does_not_create_standalone_checkpoints(self) -> None:
        self.registry(descriptor("files", base=True), enabled=set())
        async with lifecycle.lifespan(None):
            self.assertFalse(any(t.get_name() == "suite-recovery-checkpoint" for t in asyncio.all_tasks()))
        self.checkpoint.assert_not_called()


class LiveModuleRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_is_idempotent_stop_drains_and_reenable_creates_new_worker(self):
        events = []

        async def worker():
            events.append('start')
            try:
                await asyncio.Event().wait()
            finally:
                events.append('stop')

        owner = descriptor('optional', background_tasks_hook=lambda: [('live-worker', worker())])
        runtime = lifecycle.ModuleRuntime()
        with patch.object(lifecycle, 'get_user_db', side_effect=lambda: nullcontext(object())):
            runtime.start(owner)
            runtime.start(owner)
            await asyncio.sleep(0)
            self.assertEqual(events, ['start'])
            await runtime.stop(owner.slug)
            self.assertEqual(events, ['start', 'stop'])
            runtime.start(owner)
            await asyncio.sleep(0)
            await runtime.stop(owner.slug)
        self.assertEqual(events, ['start', 'stop', 'start', 'stop'])
        self.assertEqual(runtime.tasks, {})

    async def test_cancel_waits_for_thread_to_finish(self):
        import threading
        from modules.danbooru.automation import drainable_thread_call

        started, release, finished = threading.Event(), threading.Event(), threading.Event()

        def work():
            started.set()
            release.wait(5)
            finished.set()

        task = asyncio.create_task(drainable_thread_call(work))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            task.cancel()
            await asyncio.sleep(0.02)
            self.assertFalse(task.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(finished.is_set())
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_worker_failure_cancels_siblings_and_retry_starts_one_set(self):
        crash, stopped = asyncio.Event(), asyncio.Event()
        runtime = lifecycle.ModuleRuntime()

        async def broken():
            await crash.wait()
            raise RuntimeError("fixture worker crash")

        async def sibling():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        owner = descriptor("optional", background_tasks_hook=lambda: [
            ("broken-worker", broken()), ("sibling-worker", sibling())])
        with patch.object(lifecycle, 'get_user_db', side_effect=lambda: nullcontext(object())):
            with self.assertLogs("lifecycle", level="ERROR"):
                runtime.start(owner)
                await asyncio.sleep(0)
                crash.set()
                await asyncio.wait_for(stopped.wait(), 2)
                self.assertEqual(runtime.status("optional")["state"], "failed")
            await runtime.stop("optional")
            crash.clear()
            runtime.start(owner)
            runtime.start(owner)
            self.assertEqual(len(runtime.tasks["optional"]), 2)
            self.assertEqual(runtime.status("optional")["state"], "running")
            await runtime.stop("optional")
            self.assertEqual(runtime.status("optional")["state"], "disabled")

    async def test_multiple_worker_failures_do_not_cancel_thread_cleanup_twice(self):
        import threading
        from modules.danbooru.automation import drainable_thread_call
        started, release = threading.Event(), threading.Event()
        crash = asyncio.Event()
        runtime = lifecycle.ModuleRuntime()

        def work():
            started.set()
            release.wait(5)

        async def broken():
            await crash.wait()
            raise RuntimeError("fixture simultaneous failure")

        owner = descriptor("optional", background_tasks_hook=lambda: [
            ("broken-one", broken()), ("broken-two", broken()),
            ("draining-thread", drainable_thread_call(work))])
        with patch.object(lifecycle, 'get_user_db', side_effect=lambda: nullcontext(object())):
            try:
                with self.assertLogs("lifecycle", level="ERROR"):
                    runtime.start(owner)
                    self.assertTrue(await asyncio.to_thread(started.wait, 2))
                    crash.set()
                    await asyncio.sleep(.02)
                    self.assertFalse(runtime.tasks["optional"][2].done())
                    stopping = asyncio.create_task(runtime.stop("optional"))
                    await asyncio.sleep(.02)
                    self.assertFalse(stopping.done())
                    release.set()
                    await asyncio.wait_for(stopping, 2)
            finally:
                release.set()
                await runtime.stop("optional")

    async def test_live_routes_serialize_and_stop_before_persisting_disable(self):
        from routers import suite
        events = []
        enabled = set()
        runtime = lifecycle.ModuleRuntime()

        async def worker():
            events.append('start')
            try:
                await asyncio.Event().wait()
            finally:
                events.append('stop')

        owner = descriptor('optional', background_tasks_hook=lambda: [('toggle-worker', worker())])

        def persist(connection, slug, value):
            events.append('enabled' if value else 'disabled')
            if value:
                enabled.add(slug)
            else:
                self.assertNotIn(slug, runtime.tasks)
                enabled.discard(slug)

        with ExitStack() as stack:
            stack.enter_context(patch.object(suite.suite_modules, 'MODULE_REGISTRY', ModuleRegistry((descriptor("files", base=True), owner))))
            stack.enter_context(patch.object(suite, 'get_user_db', side_effect=lambda: nullcontext(object())))
            stack.enter_context(patch.object(lifecycle, 'get_user_db', side_effect=lambda: nullcontext(object())))
            stack.enter_context(patch.object(lifecycle, 'module_runtime', runtime))
            stack.enter_context(patch.object(suite.suite_modules, 'ensure_schema'))
            stack.enter_context(patch.object(suite.suite_modules, 'enabled_ids', side_effect=lambda conn: set(enabled)))
            stack.enter_context(patch.object(suite.suite_modules, 'set_enabled', side_effect=persist))
            initialize = stack.enter_context(patch.object(suite, 'init_data_db'))
            stack.enter_context(patch.object(suite, 'init_user_db'))
            try:
                await asyncio.gather(*(asyncio.to_thread(suite.enable_module, 'optional') for _ in range(3)))
                self.assertEqual(events.count('start'), 1)
                initialize.assert_called_once()
                await asyncio.to_thread(suite.disable_module, 'optional')
                self.assertLess(events.index('stop'), events.index('disabled'))
                await asyncio.to_thread(suite.enable_module, 'optional')
                self.assertEqual(events.count('start'), 2)
                with patch.object(suite.suite_modules, 'set_enabled', side_effect=RuntimeError('fixture write failure')):
                    from fastapi import HTTPException
                    with self.assertRaises(HTTPException):
                        await asyncio.to_thread(suite.disable_module, 'optional')
                self.assertIn('optional', enabled)
                self.assertIn('optional', runtime.tasks)
                self.assertEqual(events.count('start'), 3)
            finally:
                await runtime.stop('optional')


if __name__ == "__main__":
    unittest.main()
