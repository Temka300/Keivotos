from __future__ import annotations

import shutil
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database  # noqa: E402
from models import UserSettingUpdate  # noqa: E402
from routers import stats  # noqa: E402
from schema import ensure_data_schema  # noqa: E402


class SharedSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-schema"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_additive_migration_supports_backend_dictionary_rows(self) -> None:
        connection = sqlite3.connect(self.temp / "data.sqlite")
        connection.execute(
            """CREATE TABLE files (
                   id INTEGER PRIMARY KEY, path TEXT UNIQUE, folder TEXT, name TEXT,
                   ext TEXT, size INTEGER, local_md5 TEXT, downloaded_at TEXT,
                   matched_md5 TEXT, matched_by TEXT
               )"""
        )
        connection.row_factory = lambda cursor, row: {
            description[0]: value for description, value in zip(cursor.description, row)
        }
        ensure_data_schema(connection)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(files)")}
        indexes = {row["name"] for row in connection.execute("PRAGMA index_list(files)")}
        connection.close()
        self.assertIn("root_id", columns)
        self.assertIn("relative_path", columns)
        self.assertIn("idx_files_root_relative", indexes)

        user_database = self.temp / "user.sqlite"
        missing_data_database = self.temp / "missing-data.sqlite"
        with (
            patch.object(database, "USER_DB_PATH", user_database),
            patch.object(database, "DATA_DB_PATH", missing_data_database),
        ):
            database.init_user_db()
            with database.get_user_db() as user_connection:
                tables = {
                    row["name"]
                    for row in user_connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertIn("user_settings", tables)
            self.assertEqual(stats.get_user_setting("profile_name").value, "Keivotos")
            saved = stats.put_user_setting(
                "profile_name",
                UserSettingUpdate(value="  Local Curator  "),
            )
            self.assertEqual(saved.value, "Local Curator")
            self.assertEqual(stats.get_user_setting("profile_name").value, "Local Curator")
            reset = stats.put_user_setting("profile_name", UserSettingUpdate(value="   "))
            self.assertEqual(reset.value, "Keivotos")


if __name__ == "__main__":
    unittest.main()
