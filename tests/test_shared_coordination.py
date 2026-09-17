"""Protect connection lifetime and maintenance/tool exclusion during extraction."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database
from modules.danbooru import tools


class SharedCoordinationTests(unittest.TestCase):
    def test_consumers_share_gate_locks_and_owner_state(self):
        import backup_bundle
        import database_connections
        import maintenance
        from modules.danbooru import automation
        from routers import backups

        self.assertIs(database._database_access_gate, database_connections._database_access_gate)
        self.assertIs(database.exclusive_database_access, database_connections.exclusive_database_access)
        self.assertIs(backup_bundle.exclusive_database_access, database_connections.exclusive_database_access)
        self.assertIs(tools._tool_state_lock, maintenance._tool_state_lock)
        self.assertIs(tools._tool_operation_lock, maintenance._tool_operation_lock)
        self.assertIs(backups.exclusive_tool_operation, maintenance.exclusive_tool_operation)
        self.assertIs(automation.exclusive_tool_operation, maintenance.exclusive_tool_operation)
        with patch.object(maintenance, "_active_tool_id", "fixture"):
            self.assertEqual(tools.active_tool_id(), "fixture")
            self.assertEqual(tools._launch_tool("fixture", []), {"status": "already_running", "active_tool_id": "fixture"})
            self.assertEqual(tools._launch_tool("other", []), {"status": "busy", "active_tool_id": "fixture"})

    def test_connections_keep_pragmas_dictionary_rows_and_close_on_error(self):
        with tempfile.TemporaryDirectory() as temp:
            for name, factory in (("DATA_DB_PATH", database.get_data_db), ("USER_DB_PATH", database.get_user_db)):
                with self.subTest(name=name), patch.object(database, name, Path(temp) / (name + ".sqlite")):
                    with self.assertRaisesRegex(ValueError, "fixture"):
                        with factory() as conn:
                            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone(), {"journal_mode": "wal"})
                            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone(), {"foreign_keys": 1})
                            raise ValueError("fixture")
                    with self.assertRaises(sqlite3.ProgrammingError):
                        conn.execute("SELECT 1")

    def test_restore_gate_allows_nested_owner_and_blocks_other_connections(self):
        entered, attempting = threading.Event(), threading.Event()
        errors = []
        with tempfile.TemporaryDirectory() as temp, patch.object(database, "USER_DB_PATH", Path(temp) / "user.sqlite"):
            def reader():
                attempting.set()
                try:
                    with database.get_user_db():
                        entered.set()
                except Exception as exc:
                    errors.append(exc)

            thread = threading.Thread(target=reader)
            with database.exclusive_database_access():
                with database.exclusive_database_access(), database.get_user_db() as conn:
                    self.assertEqual(conn.execute("SELECT 1 AS n").fetchone(), {"n": 1})
                thread.start()
                self.assertTrue(attempting.wait(2))
                self.assertFalse(entered.wait(.1))
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertTrue(entered.is_set())
            self.assertEqual(errors, [])

    def test_maintenance_blocks_tool_launch_until_window_closes(self):
        attempting, finished = threading.Event(), threading.Event()
        results = []

        def launch():
            attempting.set()
            results.append(tools._launch_tool("coordination-fixture", []))
            finished.set()

        thread = threading.Thread(target=launch)
        with tools.exclusive_tool_operation("fixture maintenance"):
            thread.start()
            self.assertTrue(attempting.wait(2))
            self.assertFalse(finished.wait(.1))
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [{"status": "started"}])
        # The empty fixture job performs no subprocess or data operation.
        import time
        deadline = time.monotonic() + 3
        while tools.active_tool_id() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertIsNone(tools.active_tool_id())
        tools._running_tasks.pop("coordination-fixture", None)
