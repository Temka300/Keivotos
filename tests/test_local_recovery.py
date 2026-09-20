from __future__ import annotations

import shutil
import os
from datetime import datetime, timezone
from unittest.mock import patch
import sqlite3
from contextlib import closing
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
        self.legacy = self.temp / "legacy"
        self.archive = self.temp / "preserved"
        self.patches = [
            patch.object(local_recovery, "LEGACY_USER_CHECKPOINT_DIRS", (self.legacy,)),
            patch.object(local_recovery, "PRESERVED_CHECKPOINT_DIR", self.archive),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

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

    def legacy_snapshot(self, directory: Path | None = None) -> Path:
        directory = directory or self.legacy
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "user_20260101_000000_000000_startup.sqlite"
        shutil.copy2(self.user_db, target)
        return target

    def test_legacy_checkpoints_are_verified_preserved_and_not_rotated(self) -> None:
        original = self.legacy_snapshot()
        original_bytes = original.read_bytes()
        original_mtime = original.stat().st_mtime_ns
        first = local_recovery.create_local_recovery_checkpoint()
        self.assertEqual(first["preserved_count"], 1)
        for number in range(7):
            self.change_database(str(number))
            status = local_recovery.create_local_recovery_checkpoint()
        self.assertEqual(status["count"], 5)
        self.assertEqual(status["preserved_count"], 1)
        archived = list(self.archive.rglob("user_*.sqlite"))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), original_bytes)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual(original.stat().st_mtime_ns, original_mtime)

    def test_same_filename_different_sources_and_changed_bytes_are_preserved(self) -> None:
        first = self.legacy_snapshot()
        first_bytes = first.read_bytes()
        self.change_database("second")
        other = self.temp / "other"
        second = self.legacy_snapshot(other)
        with patch.object(local_recovery, "LEGACY_USER_CHECKPOINT_DIRS", (self.legacy, other)):
            local_recovery.create_local_recovery_checkpoint()
            self.assertEqual(local_recovery.local_recovery_status()["preserved_count"], 2)
            # Simulate a later legacy writer replacing its own file; suite copies stay.
            shutil.copy2(second, first)
            local_recovery.create_local_recovery_checkpoint()
        archived = list(self.archive.rglob("user_*.sqlite"))
        self.assertEqual(len(archived), 3)
        self.assertIn(first_bytes, [path.read_bytes() for path in archived])

    def test_conflicting_archive_is_not_overwritten_and_new_recovery_continues(self) -> None:
        original = self.legacy_snapshot()
        local_recovery.create_local_recovery_checkpoint()
        archived = next(self.archive.rglob("user_*.sqlite"))
        archived.write_bytes(b"fixture conflicting archive")
        self.change_database("new")
        with self.assertLogs("local_recovery", level="WARNING"):
            result = local_recovery.create_local_recovery_checkpoint()
        self.assertTrue(result["created"])
        self.assertEqual(archived.read_bytes(), b"fixture conflicting archive")
        self.assertNotEqual(original.read_bytes(), archived.read_bytes())

    def test_copy_failure_preserves_source_and_cleans_staging(self) -> None:
        original = self.legacy_snapshot()
        original_bytes = original.read_bytes()
        with patch.object(local_recovery.shutil, "copy2", side_effect=OSError("fixture interrupted copy")):
            with self.assertLogs("local_recovery", level="WARNING"):
                result = local_recovery.create_local_recovery_checkpoint()
        self.assertTrue(result["created"])
        self.assertEqual(result["preserved_count"], 0)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertFalse(list(self.archive.rglob("*.partial")))
        self.assertEqual(local_recovery.create_local_recovery_checkpoint()["preserved_count"], 1)

    def test_legacy_links_are_not_followed(self) -> None:
        self.legacy.mkdir()
        link = self.legacy / "user_link.sqlite"
        try:
            link.symlink_to(self.user_db)
        except OSError:
            self.skipTest("Symbolic links are unavailable")
        with self.assertLogs("local_recovery", level="WARNING"):
            result = local_recovery.create_local_recovery_checkpoint()
        self.assertEqual(result["preserved_count"], 0)
        self.assertTrue(link.is_symlink())

    def test_metadata_flattening_leaves_recovery_originals_in_place(self) -> None:
        import config
        target = self.temp / "module"
        legacy = target / "metadata"
        original = self.legacy_snapshot(legacy / "local_recovery" / "user_database")
        original_bytes = original.read_bytes()
        (legacy / "example.txt").write_text("fixture")
        with patch.object(config, "METADATA_DIR", target), patch.object(config, "DEFAULT_METADATA_DIR", target), patch.object(config, "LEGACY_DEFAULT_METADATA_DIR", legacy):
            result = config.migrate_legacy_default_metadata()
        self.assertTrue(result["migrated"])
        self.assertTrue((target / "example.txt").exists())
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertFalse((target / "local_recovery").exists())

    def test_same_clock_tick_preserves_distinct_checkpoints_and_rotation(self) -> None:
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

        snapshot = local_recovery._snapshot

        def snapshot_with_coarse_mtime(source, destination):
            snapshot(source, destination)
            os.utime(destination, ns=(1_800_000_000_000_000_000,) * 2)

        with patch.object(local_recovery, "datetime", FrozenDateTime), patch.object(
            local_recovery, "_snapshot", side_effect=snapshot_with_coarse_mtime
        ):
            first = local_recovery.create_local_recovery_checkpoint("sync")
            first_path = Path(first["latest_path"])
            first_bytes = first_path.read_bytes()
            self.change_database("second")
            second = local_recovery.create_local_recovery_checkpoint("sync")
            self.assertEqual(second["count"], 2)
            self.assertNotEqual(second["latest_path"], first["latest_path"])
            self.assertEqual(first_path.read_bytes(), first_bytes)
            for number in range(6):
                self.change_database(f"next-{number}")
                result = local_recovery.create_local_recovery_checkpoint("sync")
            self.assertEqual(result["count"], 5)
            with closing(sqlite3.connect(result["latest_path"])) as connection, connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 8)
            unchanged = local_recovery.create_local_recovery_checkpoint("sync")
            self.assertFalse(unchanged["created"])
            self.assertEqual(unchanged["latest_path"], result["latest_path"])
            self.assertFalse(list(self.checkpoints.glob("*.partial")))

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


    def test_retired_api_and_status_preserve_existing_copies(self):
        from fastapi import HTTPException
        from routers.recovery import create_recovery_checkpoint
        self.checkpoints.mkdir()
        self.archive.mkdir()
        shutil.copy2(self.user_db, self.checkpoints / 'user_historical.sqlite')
        shutil.copy2(self.user_db, self.archive / 'user_preserved.sqlite')
        before = {str(p): p.read_bytes() for p in self.temp.rglob('*') if p.is_file()}
        status = local_recovery.local_recovery_status()
        self.assertFalse(status['enabled'])
        self.assertEqual(status['count'], 1)
        with self.assertRaises(HTTPException) as caught:
            create_recovery_checkpoint()
        self.assertEqual(caught.exception.status_code, 410)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.temp.rglob('*') if p.is_file()})


if __name__ == "__main__":
    unittest.main()
