from __future__ import annotations

import shutil
import sys
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import automation  # noqa: E402
from automation import find_changed_media_candidates  # noqa: E402


class AutomationCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
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
            manifest[str(path.resolve()).lower()] = (stat.st_mtime_ns, stat.st_size)
        changed_media.write_bytes(b"changed fixture is a different size")
        new_media.write_bytes(b"new")

        candidates = find_changed_media_candidates([self.temp, self.temp], manifest)

        self.assertEqual(candidates, sorted([changed_media.resolve(), new_media.resolve()], key=lambda item: str(item).casefold()))

    def test_unavailable_roots_are_ignored(self) -> None:
        self.assertEqual(find_changed_media_candidates([self.temp / "missing"], {}), [])

    def test_watcher_always_uses_the_incremental_sync_path(self) -> None:
        launched: dict[str, object] = {}

        class EmptyDatabase:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, _query):
                return []

        fake_core = types.SimpleNamespace(
            active_tool_id=lambda: None,
            exclusive_tool_operation=lambda _name: nullcontext(),
            _sync_scan_paths=lambda: [self.temp],
            get_data_db=lambda: EmptyDatabase(),
            _sync_command=lambda roots: ["sync", *map(str, roots)],
            _launch_tool=lambda tool_id, commands, stage_names=None: launched.update(
                tool_id=tool_id,
                commands=commands,
                stage_names=stage_names,
            ),
        )
        with patch.object(
            automation,
            "get_automation_config",
            return_value={"enabled": True, "enabled_at": "2026-07-14T00:00:00+00:00", "interval_minutes": 15},
        ), patch.object(
            automation,
            "find_changed_media_candidates",
            return_value=[self.temp / "new.png"],
        ), patch.dict(sys.modules, {"core": fake_core}):
            automation.run_automation_tick()

        self.assertEqual(launched["tool_id"], "sync")
        self.assertEqual(launched["commands"], [["sync", str(self.temp)]])
        self.assertEqual(launched["stage_names"], ["Sync new and changed files"])


if __name__ == "__main__":
    unittest.main()
