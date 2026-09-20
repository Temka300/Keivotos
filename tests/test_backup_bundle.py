from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
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
        self.user_db = self.temp / "user.sqlite"
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
            "RECOVERY_DIR": backup_bundle.RECOVERY_DIR,
            "METADATA_DIR": backup_bundle.METADATA_DIR,
            "USER_DB_PATH": backup_bundle.USER_DB_PATH,
            "DATA_DB_PATH": backup_bundle.DATA_DB_PATH,
            "SIDECAR_DIR": backup_bundle.SIDECAR_DIR,
            "ARTIST_PROFILE_ARCHIVE_DIR": backup_bundle.ARTIST_PROFILE_ARCHIVE_DIR,
            "COMPONENTS": backup_bundle.COMPONENTS,
            "get_backup_config": backup_bundle.get_backup_config,
        }
        backup_bundle.RECOVERY_DIR = self.temp / "local_recovery"
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

    def test_disabled_owner_data_remains_eligible(self) -> None:
        import suite_modules
        with patch.object(suite_modules, "enabled_ids", side_effect=AssertionError("Backup must not gate on enablement")):
            created = backup_bundle.create_backup_bundle()
        manifest = backup_bundle.inspect_backup_bundle(Path(created["path"]))
        self.assertTrue(manifest["components"]["library_database"])
        self.assertEqual(manifest["component_owners"]["user_database"], "suite")
        self.assertEqual(manifest["component_owners"]["file_attachments"], "files")
        self.assertEqual(manifest["component_owners"]["sidecars"], "danbooru")
        with zipfile.ZipFile(created["path"]) as archive:
            self.assertIn("databases/danbooru.sqlite", archive.namelist())
            self.assertEqual(archive.read("sidecars/sample.json"), b"original-sidecar")

    def test_missing_optional_artifacts_are_reported_without_creating_them(self) -> None:
        self.data_db.unlink()  # Disposable fixture only.
        created = backup_bundle.create_backup_bundle()
        manifest = backup_bundle.inspect_backup_bundle(Path(created["path"]))
        self.assertFalse(manifest["components"]["library_database"])
        self.assertTrue(manifest["requested_components"]["library_database"])
        self.assertIn("library_database", created["omitted_components"])
        self.assertFalse(self.data_db.exists())
        self.assertTrue(backup_bundle.get_backup_config()["components"]["library_database"])

    def test_unavailable_owner_restore_rejects_before_mutation(self) -> None:
        self.destination.mkdir(parents=True)
        path = self.destination / "unknown.keivotosbk"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("manifest.json", json.dumps({
                "format": backup_bundle.BACKUP_FORMAT, "format_version": 1,
                "components": {"unknown_owner_data": True}, "files": [],
            }))
        original = self.user_db.read_bytes()
        with self.assertRaisesRegex(ValueError, "restore support is unavailable"):
            backup_bundle.restore_backup_bundle(path.name)
        self.assertEqual(self.user_db.read_bytes(), original)
        self.assertFalse((self.metadata / "local_recovery").exists())

    def _rewrite_bundle(self, created, mutate):
        path = Path(created["path"])
        with zipfile.ZipFile(path) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(contents["manifest.json"])
        mutate(contents, manifest)
        contents["manifest.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in contents.items():
                # Construct exact archive names: ZipInfo(name) would normalize
                # backslashes on Windows and silently repair the unsafe fixture.
                info = zipfile.ZipInfo()
                info.filename = name
                archive.writestr(info, data)

    def test_restore_uses_manifest_selection_and_suite_recovery(self):
        created = backup_bundle.create_backup_bundle()
        def select_user(contents, manifest):
            manifest["components"] = {"user_database": True}
        self._rewrite_bundle(created, select_user)
        (self.sidecars / "sample.json").write_text("keep-current")
        first = backup_bundle.restore_backup_bundle(created["name"])
        second = backup_bundle.restore_backup_bundle(created["name"])
        self.assertNotEqual(first["rollback_path"], second["rollback_path"])
        self.assertEqual(Path(first["rollback_path"]).parent, backup_bundle.RECOVERY_DIR)
        self.assertTrue((Path(first["rollback_path"]) / "user_database").is_file())
        self.assertFalse(first["components"]["library_database"])
        self.assertEqual((self.sidecars / "sample.json").read_text(), "keep-current")

    def test_install_failure_restores_every_previous_component(self):
        created = backup_bundle.create_backup_bundle()
        with closing(sqlite3.connect(self.user_db)) as connection, connection:
            connection.execute("UPDATE marker SET value='newer-user'")
        (self.sidecars / "sample.json").write_text("newer-sidecar")
        original_replace = Path.replace
        def fail_install(path, target):
            if path.name == "incoming" and target == self.sidecars:
                raise OSError("injected install failure")
            return original_replace(path, target)
        with patch.object(Path, "replace", fail_install), self.assertRaisesRegex(OSError, "injected"):
            backup_bundle.restore_backup_bundle(created["name"])
        with closing(sqlite3.connect(self.user_db)) as connection, connection:
            self.assertEqual(connection.execute("SELECT value FROM marker").fetchone()[0], "newer-user")
        self.assertEqual((self.sidecars / "sample.json").read_text(), "newer-sidecar")
        recovery = next(backup_bundle.RECOVERY_DIR.glob("restore_*"))
        self.assertEqual((recovery / "sidecars" / "sample.json").read_text(), "newer-sidecar")

    def test_failed_rollback_retains_local_originals_and_suite_copy(self):
        created = backup_bundle.create_backup_bundle()
        original_replace = Path.replace
        def fail_install_and_rollback(path, target):
            if (path.name == "incoming" and target == self.sidecars) or path.name == "previous-0":
                raise OSError("injected filesystem failure")
            return original_replace(path, target)
        with patch.object(Path, "replace", fail_install_and_rollback), self.assertRaisesRegex(RuntimeError, "needs recovery"):
            backup_bundle.restore_backup_bundle(created["name"])
        self.assertTrue(list(self.temp.rglob("previous-0")))
        recovery = next(backup_bundle.RECOVERY_DIR.glob("restore_*"))
        self.assertTrue((recovery / "user_database").is_file())
        self.assertEqual((recovery / "sidecars" / "sample.json").read_text(), "original-sidecar")

    def test_restore_does_not_require_cross_volume_rename(self):
        created = backup_bundle.create_backup_bundle()
        original_replace = Path.replace
        def same_parent_only(path, target):
            # Incoming and previous paths must be siblings of the live target.
            if path.parent != target.parent and path.parent.parent != target.parent and target.parent.parent != path.parent:
                raise OSError("cross-volume rename")
            return original_replace(path, target)
        with patch.object(Path, "replace", same_parent_only):
            backup_bundle.restore_backup_bundle(created["name"])

    def test_busy_wal_database_is_not_replaced(self):
        created = backup_bundle.create_backup_bundle()
        writer = sqlite3.connect(self.user_db)
        reader = sqlite3.connect(self.user_db)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM marker").fetchall()
            writer.execute("UPDATE marker SET value='wal-current'")
            writer.commit()
            with self.assertRaisesRegex(RuntimeError, "busy"):
                backup_bundle.restore_backup_bundle(created["name"])
            self.assertEqual(writer.execute("SELECT value FROM marker").fetchone()[0], "wal-current")
        finally:
            reader.close()
            writer.close()

    def test_unsafe_archive_rejected_before_live_changes(self):
        for name in ("../escaped", "C:/escaped", "sidecars/../../escaped", "sidecars\\escaped", "sidecars/null\x00ignored"):
            with self.subTest(name=name):
                created = backup_bundle.create_backup_bundle()
                self._rewrite_bundle(created, lambda contents, manifest: contents.update({name: b"bad"}))
                with zipfile.ZipFile(created["path"]) as archive:
                    self.assertIn(name, [info.orig_filename for info in archive.infolist()])
                before = self.user_db.read_bytes()
                with self.assertRaisesRegex(ValueError, "Unsafe backup entry"):
                    backup_bundle.restore_backup_bundle(created["name"])
                self.assertEqual(self.user_db.read_bytes(), before)

    def test_repeated_backup_estimates_reuse_component_scan(self) -> None:
        with patch.object(backup_bundle, "_tree_stats", wraps=backup_bundle._tree_stats) as tree_stats:
            first = backup_bundle.backup_estimate()
            second = backup_bundle.backup_estimate()

        self.assertEqual(first, second)
        self.assertEqual(tree_stats.call_count, 3)

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


class BackupComponentDeclarationTests(unittest.TestCase):
    def test_owner_catalog_preserves_legacy_keys_and_paths(self) -> None:
        catalog = backup_bundle.collect_backup_components()
        self.assertEqual({key: c.owner for key, c in catalog.items()}, {
            "user_database": "suite", "file_attachments": "files",
            "library_database": "danbooru", "sidecars": "danbooru",
            "sidecar_history": "danbooru", "artist_profile_archive": "danbooru",
        })
        self.assertEqual(catalog["library_database"].archive_name, "databases/danbooru.sqlite")
        self.assertEqual(catalog["user_database"].archive_name, "databases/user.sqlite")
        self.assertNotIn("files_database", catalog)

    def test_invalid_duplicate_and_overlapping_declarations_are_rejected(self) -> None:
        from dataclasses import replace
        from module_descriptor import BackupComponent
        owner = backup_bundle.MODULE_REGISTRY.require("danbooru")
        invalid = [
            BackupComponent("user_database", "danbooru", "other", "tree", Path("unused")),
            BackupComponent("fixture", "wrong", "other", "tree", Path("unused")),
            BackupComponent("fixture", "danbooru", "../escape", "tree", Path("unused")),
            BackupComponent("fixture", "danbooru", ".", "tree", Path("unused")),
            BackupComponent("../fixture", "danbooru", "other", "tree", Path("unused")),
            BackupComponent("fixture", "danbooru", "databases", "tree", Path("unused")),
            BackupComponent("fixture", "danbooru", "config.json", "tree", Path("unused")),
        ]
        for component in invalid:
            registry = backup_bundle.MODULE_REGISTRY.replacing(replace(owner, backup_components_provider=lambda c=component: (c,)))
            with self.subTest(component=component), self.assertRaises(ValueError):
                backup_bundle.collect_backup_components(registry)

    def test_missing_owner_preferences_survive_saving_suite_selection(self) -> None:
        configured = {"user_database": True, "file_attachments": True, "library_database": False}
        components = {"user_database": ("databases/user.sqlite", Path("unused"))}
        with patch.object(backup_bundle, "COMPONENTS", components), patch.object(
            backup_bundle, "get_backup_config", return_value={"components": configured}
        ), patch.object(backup_bundle, "backup_configuration", return_value={}), patch.object(backup_bundle, "save_config") as save:
            backup_bundle.update_backup_configuration({"user_database": True, "file_attachments": False})
        self.assertIn("library_database", save.call_args.args[0]["backup_components"])
        self.assertFalse(save.call_args.args[0]["backup_components"]["library_database"])


class AttachmentBackupTests(unittest.TestCase):
    """The Files-base attachment byte-store backup/restore (the durability goal)."""

    def _prepare(self):
        from files_base import annotations, attachment_store

        self.temp = ROOT / "tests" / ".tmp-attach-backup"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.metadata = self.temp / "metadata"
        self.destination = self.temp / "backups"
        self.store_root = self.temp / "library"  # the user's "first Files folder"
        self.user_db = self.temp / "user.sqlite"
        self.metadata.mkdir(parents=True)
        self.store_root.mkdir(parents=True)

        self.data = b"a-real-screenshot-bytes"
        self.hash = attachment_store.md5_bytes(self.data)
        attachment_store.write_attachment(self.store_root, self.hash, "png", self.data)
        self.stored_path = attachment_store.attachment_path(self.store_root, self.hash, "png")

        connection = sqlite3.connect(self.user_db)
        connection.row_factory = sqlite3.Row
        annotations.ensure_annotations_schema(connection)
        note = annotations.upsert_annotation(
            connection, subject_kind="file", content_hash="deadbeef", source_id="s", relative_path="model.zip"
        )
        annotations.add_attachment(
            connection, note.id, content_hash=self.hash, file_name="shot.png",
            media_type="image/png", size=len(self.data), stored_root=str(self.store_root),
        )
        connection.close()

        self.originals = {
            "RECOVERY_DIR": backup_bundle.RECOVERY_DIR,
            "METADATA_DIR": backup_bundle.METADATA_DIR,
            "USER_DB_PATH": backup_bundle.USER_DB_PATH,
            "DATA_DB_PATH": backup_bundle.DATA_DB_PATH,
            "SIDECAR_DIR": backup_bundle.SIDECAR_DIR,
            "COMPONENTS": backup_bundle.COMPONENTS,
            "get_backup_config": backup_bundle.get_backup_config,
        }
        backup_bundle.RECOVERY_DIR = self.temp / "local_recovery"
        backup_bundle.METADATA_DIR = self.metadata
        backup_bundle.USER_DB_PATH = self.user_db
        backup_bundle.DATA_DB_PATH = self.metadata / "danbooru.sqlite"
        backup_bundle.SIDECAR_DIR = self.metadata / "sidecars"
        backup_bundle.COMPONENTS = {
            "user_database": ("databases/user.sqlite", self.user_db),
            "library_database": ("databases/danbooru.sqlite", backup_bundle.DATA_DB_PATH),
            "sidecars": ("sidecars", backup_bundle.SIDECAR_DIR),
            "sidecar_history": ("sidecar_archive", self.metadata / "sidecar_archive"),
            "artist_profile_archive": ("artist_profile_archive", self.metadata / "artist_profile_archive"),
        }
        backup_bundle.get_backup_config = lambda: {
            "destination": str(self.destination),
            "components": {"user_database": True, "file_attachments": True},
        }
        backup_bundle._estimate_cache.clear()

    def _teardown(self) -> None:
        for name, value in getattr(self, "originals", {}).items():
            setattr(backup_bundle, name, value)
        backup_bundle._estimate_cache.clear()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_attachment_bytes_backup_survive_folder_loss_and_restore(self) -> None:
        self._prepare()
        try:
            estimate = backup_bundle.backup_estimate()
            self.assertEqual(estimate["details"]["file_attachments"]["files"], 1)

            created = backup_bundle.create_backup_bundle()
            with zipfile.ZipFile(created["path"], "r") as archive:
                names = archive.namelist()
            self.assertIn(f"file_attachments/{self.hash}.png", names)

            # Simulate the user's folder backup being gone: the bytes vanish.
            self.stored_path.unlink()
            self.assertFalse(self.stored_path.exists())

            backup_bundle.restore_backup_bundle(created["name"])

            # The Keivotos bundle brought the screenshot back to its folder.
            self.assertTrue(self.stored_path.is_file())
            self.assertEqual(self.stored_path.read_bytes(), self.data)
        finally:
            self._teardown()

    def test_visible_attachment_is_backed_up_and_preserved(self):
        from files_base import attachment_store
        self._prepare()
        try:
            visible = attachment_store.attachment_path(self.store_root, self.hash, "png", visible=True)
            visible.parent.mkdir()
            self.stored_path.replace(visible)
            created = backup_bundle.create_backup_bundle()
            with zipfile.ZipFile(created["path"]) as archive:
                self.assertEqual(archive.read(f"file_attachments/{self.hash}.png"), self.data)
            visible.write_bytes(b"current-visible")
            result = backup_bundle.restore_backup_bundle(created["name"])
            self.assertEqual(result["attachments"]["existing"], 1)
            self.assertEqual(visible.read_bytes(), b"current-visible")
            self.assertFalse(self.stored_path.exists())
        finally:
            self._teardown()

    def test_attachment_rows_follow_database_snapshot(self):
        self._prepare()
        try:
            snapshot = backup_bundle._sqlite_snapshot
            def snapshot_then_change(source, destination):
                snapshot(source, destination)
                with closing(sqlite3.connect(self.user_db)) as connection, connection:
                    connection.execute("DELETE FROM files_annotation_attachments")
            with patch.object(backup_bundle, "_sqlite_snapshot", snapshot_then_change):
                created = backup_bundle.create_backup_bundle()
            with zipfile.ZipFile(created["path"]) as archive:
                self.assertEqual(archive.read(f"file_attachments/{self.hash}.png"), self.data)
        finally:
            self._teardown()

    def test_corrupt_attachment_is_reported_without_publishing(self):
        self._prepare()
        try:
            created = backup_bundle.create_backup_bundle()
            path = Path(created["path"])
            with zipfile.ZipFile(path) as archive:
                contents = {name: archive.read(name) for name in archive.namelist()}
            contents[f"file_attachments/{self.hash}.png"] = b"wrong bytes"
            with zipfile.ZipFile(path, "w") as archive:
                for name, data in contents.items():
                    archive.writestr(name, data)
            self.stored_path.unlink()
            restored = backup_bundle.restore_backup_bundle(created["name"])
            self.assertFalse(self.stored_path.exists())
            self.assertEqual(restored["attachments"]["failed"], 1)
            self.assertIn("recovery incomplete", restored["message"])
        finally:
            self._teardown()

    def test_attachment_restore_on_store_without_hardlinks(self):
        import errno
        self._prepare()
        try:
            created = backup_bundle.create_backup_bundle()
            self.stored_path.unlink()
            with patch.object(backup_bundle.os, "link", side_effect=OSError(errno.EOPNOTSUPP, "unsupported")):
                result = backup_bundle.restore_backup_bundle(created["name"])
            self.assertEqual(self.stored_path.read_bytes(), self.data)
            self.assertEqual(result["attachments"]["restored"], 1)
        finally:
            self._teardown()

    def test_attachment_publication_race_never_overwrites(self):
        self._prepare()
        try:
            created = backup_bundle.create_backup_bundle()
            self.stored_path.unlink()
            def competing_writer(source, target):
                target.write_bytes(b"concurrent-user-bytes")
                raise FileExistsError("winner")
            with patch.object(backup_bundle.os, "link", competing_writer):
                restored = backup_bundle.restore_backup_bundle(created["name"])
            self.assertEqual(self.stored_path.read_bytes(), b"concurrent-user-bytes")
            self.assertEqual(restored["attachments"]["existing"], 1)
        finally:
            self._teardown()

    def test_restore_is_create_only_and_never_overwrites(self) -> None:
        self._prepare()
        try:
            created = backup_bundle.create_backup_bundle()
            # A newer/edited byte already sits at the target; restore must not clobber it.
            self.stored_path.write_bytes(b"user-current-version")
            backup_bundle.restore_backup_bundle(created["name"])
            self.assertEqual(self.stored_path.read_bytes(), b"user-current-version")
        finally:
            self._teardown()


if __name__ == "__main__":
    unittest.main()
