from __future__ import annotations

import asyncio
import os
import shutil
import sys
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from modules.danbooru import automation  # noqa: E402
from modules.danbooru.automation import find_changed_media_candidates  # noqa: E402


class AutomationCandidateTests(unittest.TestCase):
    def test_router_and_lifecycle_share_watcher_objects(self) -> None:
        from modules.danbooru import lifecycle
        from routers import tools

        self.assertIs(lifecycle.automation_loop, automation.automation_loop)
        self.assertIs(tools.automation_status, automation.automation_status)
        self.assertIs(tools.set_automation_enabled, automation.set_automation_enabled)

    def setUp(self) -> None:
        for name, value in (("_candidate_count", 0), ("_last_run_at", None)):
            override = patch.object(automation, name, value)
            override.start()
            self.addCleanup(override.stop)
        self.temp = ROOT / "tests" / ".tmp-automation"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_only_new_or_stat_changed_media_is_selected(self) -> None:
        unchanged_media = self.temp / "unchanged.jpg"
        changed_media = self.temp / "changed.png"
        new_media = self.temp / "new.webp"
        ignored_file = self.temp / "notes.txt"
        for path in (unchanged_media, changed_media, ignored_file):
            path.write_bytes(b"fixture")
        manifest = {}
        for path in (unchanged_media, changed_media):
            stat = path.stat()
            manifest[os.path.normcase(os.path.abspath(path))] = (
                stat.st_mtime_ns,
                stat.st_size,
            )
        changed_media.write_bytes(b"changed fixture is a different size")
        new_media.write_bytes(b"new")

        candidates = find_changed_media_candidates([self.temp, self.temp], manifest)

        self.assertEqual(candidates, sorted([changed_media.resolve(), new_media.resolve()], key=lambda item: str(item).casefold()))

    def test_unavailable_roots_are_ignored(self) -> None:
        self.assertEqual(find_changed_media_candidates([self.temp / "missing"], {}), [])

    def test_disabled_or_unconfirmed_watcher_does_not_scan(self) -> None:
        for enabled, enabled_at in ((False, "previous"), (True, None)):
            with self.subTest(enabled=enabled), patch.object(
                automation, "get_automation_config",
                return_value={"enabled": enabled, "enabled_at": enabled_at, "interval_minutes": 15},
            ), patch.object(automation, "_sync_scan_paths") as scan:
                self.assertEqual(automation.run_automation_tick()["candidate_count"], 0)
                scan.assert_not_called()

    def test_busy_tool_preserves_last_status_without_scanning(self) -> None:
        with patch.object(automation, "get_automation_config", return_value={
            "enabled": True, "enabled_at": "previous", "interval_minutes": 15,
        }), patch.object(automation, "exclusive_tool_operation", side_effect=RuntimeError("busy")), patch.object(
            automation, "_sync_scan_paths",
        ) as scan, patch.object(automation, "_candidate_count", 3):
            self.assertEqual(automation.run_automation_tick()["candidate_count"], 3)
            scan.assert_not_called()

    def test_toggle_clamps_interval_and_retains_enable_timestamp(self) -> None:
        config = {"enabled": False, "enabled_at": None, "interval_minutes": 15}

        def save(updates):
            config.update({key.removeprefix("automation_"): value for key, value in updates.items()})

        with patch.object(automation, "get_automation_config", side_effect=lambda: dict(config)), patch.object(
            automation, "save_config", side_effect=save,
        ):
            first = automation.set_automation_enabled(True, 1)
            self.assertTrue(first["enabled_at"])
            self.assertEqual(first["interval_minutes"], 5)
            second = automation.set_automation_enabled(True, 9999)
            self.assertEqual(second["enabled_at"], first["enabled_at"])
            self.assertEqual(second["interval_minutes"], 1440)
            automation._candidate_count = 4
            stopped = automation.set_automation_enabled(False)
            self.assertEqual(stopped["candidate_count"], 0)
            self.assertEqual(stopped["enabled_at"], first["enabled_at"])

    def test_loop_retries_tick_errors_and_propagates_cancellation(self) -> None:
        async def exercise():
            with patch.object(automation.asyncio, "to_thread", new_callable=AsyncMock) as tick, patch.object(
                automation.asyncio, "sleep", new_callable=AsyncMock,
            ) as sleep, patch.object(automation, "get_automation_config", return_value={"interval_minutes": 7}), patch.object(
                automation.logger, "exception",
            ) as logged:
                tick.side_effect = [ValueError("fixture failure"), None]
                sleep.side_effect = [None, asyncio.CancelledError()]
                with self.assertRaises(asyncio.CancelledError):
                    await automation.automation_loop()
                self.assertEqual(tick.await_count, 2)
                tick.assert_awaited_with(automation.run_automation_tick)
                self.assertEqual([call.args for call in sleep.await_args_list], [(420,), (420,)])
                logged.assert_called_once_with("Automatic library ingest tick failed")

        asyncio.run(exercise())

    def test_watcher_always_uses_the_incremental_sync_path(self) -> None:
        launched: dict[str, object] = {}

        class EmptyDatabase:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, _query):
                return []

        # The tool helpers are imported by `automation` from their owning module,
        # so they are patched on `automation` itself. This used to inject a fake
        # `core` into sys.modules, which only worked while the import was lazy.
        with patch.object(
            automation,
            "get_automation_config",
            return_value={"enabled": True, "enabled_at": "2026-07-14T00:00:00+00:00", "interval_minutes": 15},
        ), patch.object(
            automation,
            "find_changed_media_candidates",
            return_value=[self.temp / "new.png"],
        ), patch.object(
            automation, "exclusive_tool_operation", lambda _name: nullcontext()
        ), patch.object(
            automation, "_sync_scan_paths", lambda: [self.temp]
        ), patch.object(
            automation, "get_data_db", lambda: EmptyDatabase()
        ), patch.object(
            automation, "_sync_command", lambda roots: ["sync", *map(str, roots)]
        ), patch.object(
            automation,
            "_launch_tool",
            lambda tool_id, commands, stage_names=None: launched.update(
                tool_id=tool_id, commands=commands, stage_names=stage_names
            ),
        ):
            automation.run_automation_tick()

        self.assertEqual(launched["tool_id"], "sync")
        self.assertEqual(launched["commands"], [["sync", str(self.temp)]])
        self.assertEqual(launched["stage_names"], ["Sync new and changed files"])


if __name__ == "__main__":
    unittest.main()
