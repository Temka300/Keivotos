from __future__ import annotations

import shutil
import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import local_recovery  # noqa: E402


class LocalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-local-recovery"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        self.user_db = self.temp / "user.sqlite"
        self.checkpoints = self.temp / "checkpoints"
        connection = sqlite3.connect(self.user_db)
        connection.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO notes(value) VALUES ('first')")
        connection.commit()
        connection.close()
        self.original_user_db = local_recovery.USER_DB_PATH
        self.original_checkpoint_dir = local_recovery.CHECKPOINT_DIR
        self.original_retention = local_recovery.CHECKPOINT_RETENTION
        local_recovery.USER_DB_PATH = self.user_db
        local_recovery.CHECKPOINT_DIR = self.checkpoints
        local_recovery.CHECKPOINT_RETENTION = 5

    def tearDown(self) -> None:
        local_recovery.USER_DB_PATH = self.original_user_db
        local_recovery.CHECKPOINT_DIR = self.original_checkpoint_dir
        local_recovery.CHECKPOINT_RETENTION = self.original_retention
        shutil.rmtree(self.temp, ignore_errors=True)

    def change_database(self, value: str) -> None:
        connection = sqlite3.connect(self.user_db)
        connection.execute("INSERT INTO notes(value) VALUES (?)", (value,))
        connection.commit()
        connection.close()

    def test_checkpoint_is_verified_deduplicated_and_rotated(self) -> None:
        created = local_recovery.create_local_recovery_checkpoint("startup")
        self.assertTrue(created["created"])
        unchanged = local_recovery.create_local_recovery_checkpoint("sync")
        self.assertFalse(unchanged["created"])
        self.assertEqual(unchanged["count"], 1)

        for index in range(7):
            self.change_database(f"change-{index}")
            local_recovery.create_local_recovery_checkpoint("sync")

        status = local_recovery.local_recovery_status()
        self.assertEqual(status["count"], 5)
        for checkpoint in self.checkpoints.glob("*.sqlite"):
            connection = sqlite3.connect(checkpoint)
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
            connection.close()


if __name__ == "__main__":
    unittest.main()
