from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import backup_bundle  # noqa: E402
import database  # noqa: E402


class MetadataBackupBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-backup-bundle"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.metadata = self.temp / "metadata"
        self.destination = self.temp / "backups"
        self.user_db = self.metadata / "user.sqlite"
        self.data_db = self.metadata / "danbooru.sqlite"
        self.sidecars = self.metadata / "sidecars"
        self.external_image = self.temp / "external" / "original.jpg"
        self.sidecars.mkdir(parents=True)
        self.external_image.parent.mkdir(parents=True)
        self.external_image.write_bytes(b"original-image-must-stay")
        (self.sidecars / "sample.json").write_text("original-sidecar", encoding="utf-8")
        for path, value in ((self.user_db, "user-original"), (self.data_db, "library-original")):
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE marker(value TEXT)")
            connection.execute("INSERT INTO marker VALUES (?)", (value,))
            if path == self.user_db:
                connection.execute(
                    """CREATE TABLE user_settings (
                           key TEXT PRIMARY KEY,
                           value TEXT NOT NULL,
                           updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                       )"""
                )
                connection.execute(
                    "INSERT INTO user_settings(key, value) VALUES ('profile_name', 'Backup Curator')"
                )
            connection.commit()
            connection.close()

        self.originals = {
            "METADATA_DIR": backup_bundle.METADATA_DIR,
            "USER_DB_PATH": backup_bundle.USER_DB_PATH,
            "DATA_DB_PATH": backup_bundle.DATA_DB_PATH,
            "SIDECAR_DIR": backup_bundle.SIDECAR_DIR,
            "ARTIST_PROFILE_ARCHIVE_DIR": backup_bundle.ARTIST_PROFILE_ARCHIVE_DIR,
            "COMPONENTS": backup_bundle.COMPONENTS,
            "get_backup_config": backup_bundle.get_backup_config,
        }
        backup_bundle.METADATA_DIR = self.metadata
        backup_bundle.USER_DB_PATH = self.user_db
        backup_bundle.DATA_DB_PATH = self.data_db
        backup_bundle.SIDECAR_DIR = self.sidecars
        backup_bundle.ARTIST_PROFILE_ARCHIVE_DIR = self.metadata / "artist_profile_archive"
        backup_bundle.COMPONENTS = {
            "user_database": ("databases/user.sqlite", self.user_db),
            "library_database": ("databases/danbooru.sqlite", self.data_db),
            "sidecars": ("sidecars", self.sidecars),
            "sidecar_history": ("sidecar_archive", self.metadata / "sidecar_archive"),
            "artist_profile_archive": ("artist_profile_archive", backup_bundle.ARTIST_PROFILE_ARCHIVE_DIR),
        }
        backup_bundle.get_backup_config = lambda: {
            "destination": str(self.destination),
            "components": {
                "user_database": True,
                "library_database": True,
                "sidecars": True,
                "sidecar_history": False,
                "artist_profile_archive": False,
            },
        }
        backup_bundle._estimate_cache.clear()

    def tearDown(self) -> None:
        for name, value in self.originals.items():
            setattr(backup_bundle, name, value)
        backup_bundle._estimate_cache.clear()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_repeated_backup_estimates_reuse_component_scan(self) -> None:
        with patch.object(backup_bundle, "_tree_stats", wraps=backup_bundle._tree_stats) as tree_stats:
            first = backup_bundle.backup_estimate()
            second = backup_bundle.backup_estimate()

        self.assertEqual(first, second)
        self.assertEqual(tree_stats.call_count, 3)

    def test_backup_creation_feedback_is_visible_before_restore(self) -> None:
        source = (ROOT / "frontend" / "src" / "components" / "BackupRestoreSettings.svelte").read_text(encoding="utf-8")
        self.assertIn("Created ${result.name} (${result.display_size}) in ${destination}", source)
        self.assertIn("Backup location", source)
        self.assertIn("Save selection", source)
        self.assertNotIn("browseDestination", source)
        self.assertNotIn("Save location", source)
        self.assertIn('aria-live="polite"', source)
        self.assertIn("backupMessage ? 'Create another backup' : 'Create backup'", source)
        self.assertLess(source.index("{#if backupMessage}"), source.index('class="mt-4 grid gap-2 sm:grid-cols-2"'))
        self.assertLess(source.index("{#if backupMessage}"), source.index('id="setting-restore"'))

    def test_verified_bundle_restores_metadata_and_never_images(self) -> None:
        created = backup_bundle.create_backup_bundle()
        self.assertRegex(created["name"], r"^backup_\d+(?:_\d+)?\.keivotosbk$")
        manifest = backup_bundle.inspect_backup_bundle(Path(created["path"]))
        self.assertFalse(manifest["external_images_included"])
        self.assertFalse(manifest["thumbnails_included"])
        self.assertFalse(manifest["credentials_included"])
        self.assertNotIn("metadata_directory", manifest)
        with zipfile.ZipFile(created["path"], "r") as archive:
            snapshot = json.loads(archive.read("config.json"))
        for private_path in ("data_root", "metadata_dir", "gallery_dl_dir", "backup_destination"):
            self.assertNotIn(private_path, snapshot)

        for path, value in ((self.user_db, "user-mutated"), (self.data_db, "library-mutated")):
            connection = sqlite3.connect(path)
            connection.execute("UPDATE marker SET value=?", (value,))
            if path == self.user_db:
                connection.execute(
                    "UPDATE user_settings SET value='Browser-Only Impostor' WHERE key='profile_name'"
                )
            connection.commit()
            connection.close()
        (self.sidecars / "sample.json").write_text("mutated-sidecar", encoding="utf-8")

        restored = backup_bundle.restore_backup_bundle(created["name"])
        self.assertTrue(restored["restart_required"])
        for path, expected in ((self.user_db, "user-original"), (self.data_db, "library-original")):
            connection = sqlite3.connect(path)
            actual = connection.execute("SELECT value FROM marker").fetchone()[0]
            profile_name = (
                connection.execute(
                    "SELECT value FROM user_settings WHERE key='profile_name'"
                ).fetchone()[0]
                if path == self.user_db
                else None
            )
            connection.close()
            self.assertEqual(actual, expected)
            if path == self.user_db:
                self.assertEqual(profile_name, "Backup Curator")
        self.assertEqual((self.sidecars / "sample.json").read_text(encoding="utf-8"), "original-sidecar")
        self.assertEqual(self.external_image.read_bytes(), b"original-image-must-stay")
        self.assertTrue(Path(restored["rollback_path"]).is_dir())

    def test_compatibility_backup_suffix_remains_listed_and_restorable(self) -> None:
        created = backup_bundle.create_backup_bundle()
        current = Path(created["path"])
        legacy = current.with_suffix(".whbackup")
        current.replace(legacy)

        listed = backup_bundle.list_backups(self.destination)
        self.assertIn(legacy.name, [item["name"] for item in listed])
        inspected = backup_bundle.inspect_backup_bundle(legacy)
        self.assertEqual(inspected["format"], "danbooru-metadata-backup")
        restored = backup_bundle.restore_backup_bundle(legacy.name)
        self.assertEqual(restored["name"], legacy.name)

    def test_restore_waits_for_inflight_database_users(self) -> None:
        created = backup_bundle.create_backup_bundle()
        reader_entered = threading.Event()
        release_reader = threading.Event()
        restore_finished = threading.Event()
        errors: list[Exception] = []

        def hold_reader() -> None:
            with database._database_access_gate.read():
                reader_entered.set()
                release_reader.wait(timeout=5)

        def restore() -> None:
            try:
                backup_bundle.restore_backup_bundle(created["name"])
            except Exception as exc:  # pragma: no cover - asserted below.
                errors.append(exc)
            finally:
                restore_finished.set()

        reader_thread = threading.Thread(target=hold_reader)
        restore_thread = threading.Thread(target=restore)
        reader_thread.start()
        self.assertTrue(reader_entered.wait(timeout=2))
        restore_thread.start()
        self.assertFalse(restore_finished.wait(timeout=0.1))
        release_reader.set()
        reader_thread.join(timeout=5)
        restore_thread.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertTrue(restore_finished.is_set())


if __name__ == "__main__":
    unittest.main()
