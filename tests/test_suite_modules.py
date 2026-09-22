from __future__ import annotations

import shutil
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import suite_modules  # noqa: E402
from files_base.sources import Source  # noqa: E402


class SuiteModulesRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-suite-modules"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        self.conn = sqlite3.connect(self.temp / "user.sqlite")
        self.conn.row_factory = sqlite3.Row
        suite_modules.ensure_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_nothing_enabled_by_default(self) -> None:
        self.assertEqual(suite_modules.enabled_ids(self.conn), set())

    def test_enable_and_disable_roundtrip(self) -> None:
        suite_modules.set_enabled(self.conn, "danbooru", True)
        self.assertEqual(suite_modules.enabled_ids(self.conn), {"danbooru"})
        # Enabling twice is idempotent.
        suite_modules.set_enabled(self.conn, "danbooru", True)
        self.assertEqual(suite_modules.enabled_ids(self.conn), {"danbooru"})
        suite_modules.set_enabled(self.conn, "danbooru", False)
        self.assertEqual(suite_modules.enabled_ids(self.conn), set())

    def test_known_modules(self) -> None:
        self.assertTrue(suite_modules.is_known("files"))
        self.assertTrue(suite_modules.is_known("danbooru"))
        self.assertFalse(suite_modules.is_known("nope"))

    def test_required_base_cannot_be_disabled(self) -> None:
        with self.assertRaises(ValueError):
            suite_modules.set_enabled(self.conn, "files", False)
        suite_modules.set_enabled(self.conn, "files", True)
        self.assertEqual(suite_modules.enabled_ids(self.conn), set())


class SuiteApiRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-suite-api"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)

        import database
        from routers import suite

        self.suite = suite
        self._patch = patch.object(database, "USER_DB_PATH", self.temp / "user.sqlite")
        self._patch.start()
        self._data_patch = patch.object(database, "DATA_DB_PATH", self.temp / "index.sqlite")
        self._data_patch.start()
        self._migration_patch = patch("config.migrate_legacy_default_metadata", return_value={"migrated": False})
        self._migration_patch.start()


    def tearDown(self) -> None:
        self._migration_patch.stop()
        self._data_patch.stop()
        self._patch.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_list_defaults_to_disabled(self) -> None:
        modules = self.suite.list_modules()
        self.assertEqual([m.id for m in modules], ["files", "danbooru", "video", "manga", "youtube"])
        self.assertTrue(modules[0].enabled)
        self.assertTrue(modules[0].is_base)
        self.assertFalse(modules[0].disableable)
        self.assertFalse(modules[1].enabled)

    def test_enable_then_disable(self) -> None:
        enabled = self.suite.enable_module("danbooru")
        self.assertTrue(enabled.enabled)
        self.assertTrue(next(module for module in self.suite.list_modules() if module.id == "danbooru").enabled)
        disabled = self.suite.disable_module("danbooru")
        self.assertFalse(disabled.enabled)
        self.assertFalse(next(module for module in self.suite.list_modules() if module.id == "danbooru").enabled)

    def test_repeat_enable_does_not_reinitialize_storage(self) -> None:
        self.suite.enable_module("danbooru")
        with patch.object(self.suite, "init_data_db") as initialize:
            self.suite.enable_module("danbooru")
            initialize.assert_not_called()

    def test_failed_initialization_does_not_persist_enablement(self) -> None:
        from fastapi import HTTPException

        with patch.object(self.suite, "init_data_db", side_effect=RuntimeError("fixture busy")):
            with self.assertRaises(HTTPException) as caught:
                self.suite.enable_module("danbooru")
            self.assertEqual(caught.exception.status_code, 503)
        self.assertFalse(next(module for module in self.suite.list_modules() if module.id == "danbooru").enabled)

    def test_unknown_module_is_404(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            self.suite.enable_module("nope")
        self.assertEqual(caught.exception.status_code, 404)

    def test_base_disable_is_rejected(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            self.suite.disable_module("files")
        self.assertEqual(caught.exception.status_code, 409)

    def test_folder_batch_serializes_shared_source_records(self) -> None:
        source = Source("src-one", str(self.temp), "Library", "files", True, None)
        payload = self.suite.FolderBatchPayload(folders=[])
        with patch.object(
            self.suite.folder_roles,
            "apply_changes",
            return_value={
                "sources": [source],
                "adopted": [],
                "released": [],
                "forgotten": [],
                "operations": [],
            },
        ):
            result = self.suite.apply_folder_changes(payload)
        self.assertEqual(result.sources[0].source_id, "src-one")
        self.assertTrue(result.sources[0].visible)


class ModuleTransitionReservationTests(unittest.TestCase):
    def test_transition_excludes_tools_and_maintenance(self):
        import maintenance
        from modules.danbooru.tools import _launch_tool

        with maintenance.module_transition():
            self.assertEqual(_launch_tool('fixture', [])['status'], 'busy')
            with self.assertRaises(RuntimeError):
                with maintenance.exclusive_tool_operation('fixture backup'):
                    self.fail('Maintenance must not overlap a transition')
        with maintenance.exclusive_tool_operation('fixture backup'):
            pass

    def test_active_tool_rejects_transition_and_preserves_reservation(self):
        import maintenance

        with patch.object(maintenance, '_active_tool_id', 'fixture-import'):
            with self.assertRaisesRegex(RuntimeError, 'fixture-import'):
                with maintenance.module_transition():
                    self.fail('Active tools must finish first')
        self.assertFalse(maintenance._module_transition)

    def test_other_thread_maintenance_rejects_transition_without_waiting(self):
        import maintenance
        import threading

        entered, release = threading.Event(), threading.Event()
        def backup():
            with maintenance.exclusive_tool_operation('fixture backup'):
                entered.set()
                release.wait(5)
        thread = threading.Thread(target=backup)
        thread.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.assertRaisesRegex(RuntimeError, 'maintenance'):
                with maintenance.module_transition():
                    self.fail('Busy backup must reject disable')
        finally:
            release.set()
            thread.join(2)


if __name__ == "__main__":
    unittest.main()
