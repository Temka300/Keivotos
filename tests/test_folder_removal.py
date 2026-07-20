from __future__ import annotations

import shutil
import sqlite3
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from routers import folders  # noqa: E402
from schema import ensure_data_schema  # noqa: E402
from storage_layout import legacy_hashed_sidecar_path  # noqa: E402


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return dict(zip((column[0] for column in cursor.description), row))


class FolderRemovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-folder-removal"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.library = self.temp / "external-library"
        self.media = self.library / "characters" / "sample.jpg"
        self.media.parent.mkdir(parents=True)
        self.media.write_bytes(b"external-original")

        self.data_root = self.temp / "portable-data"
        self.sidecars = self.temp / "metadata" / "sidecars"
        self.history = self.temp / "metadata" / "sidecar_archive" / "sample.old.json"
        self.history.parent.mkdir(parents=True)
        self.history.write_text("history", encoding="utf-8")

        self.canonical_json = self.sidecars / "roots" / "root-test" / "characters" / "sample.jpg.danbooru.json"
        self.canonical_tags = self.sidecars / "roots" / "root-test" / "characters" / "sample.jpg.tags.txt"
        self.canonical_json.parent.mkdir(parents=True)
        self.canonical_json.write_text("json metadata", encoding="utf-8")
        self.canonical_tags.write_text("tag metadata", encoding="utf-8")
        self.legacy = legacy_hashed_sidecar_path(self.media, ".danbooru.json", self.sidecars)
        self.legacy.parent.mkdir(parents=True)
        self.legacy.write_text("legacy metadata", encoding="utf-8")

        self.adjacent = self.media.with_name(self.media.name + ".danbooru.json")
        self.adjacent.write_text("preservation copy", encoding="utf-8")
        self.other_root = self.sidecars / "roots" / "root-other" / "other.jpg.danbooru.json"
        self.other_root.parent.mkdir(parents=True)
        self.other_root.write_text("other root", encoding="utf-8")

        self.data_db = self.temp / "danbooru.sqlite"
        connection = sqlite3.connect(self.data_db)
        ensure_data_schema(connection)
        connection.execute(
            """INSERT INTO files
               (id, path, folder, root_id, relative_path, name, ext, size)
               VALUES (1, ?, 'external-library', 'root-test', 'characters/sample.jpg', 'sample.jpg', '.jpg', ?)""",
            (str(self.media), self.media.stat().st_size),
        )
        connection.execute("INSERT INTO posts (id, file_id) VALUES (101, 1)")
        connection.execute("INSERT INTO tags (id, name, category) VALUES (1, 'sample_tag', 'general')")
        connection.execute("INSERT INTO post_tags (post_id, tag_id) VALUES (101, 1)")
        connection.execute("INSERT INTO sync_manifest (media_path) VALUES (?)", (str(self.media),))
        connection.execute("INSERT INTO ingest_state (media_path) VALUES (?)", (str(self.media),))
        connection.commit()
        connection.close()

        self.user_db = self.temp / "user.sqlite"
        connection = sqlite3.connect(self.user_db)
        connection.execute(
            """CREATE TABLE registered_folders (
                   name TEXT PRIMARY KEY,
                   path TEXT NOT NULL,
                   root_id TEXT NOT NULL,
                   display_name TEXT
               )"""
        )
        connection.execute(
            "INSERT INTO registered_folders (name, path, root_id, display_name) VALUES ('external-library', ?, 'root-test', 'external-library')",
            (str(self.library),),
        )
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    @contextmanager
    def data_connection(self):
        connection = sqlite3.connect(self.data_db)
        connection.row_factory = _row_factory
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def user_connection(self):
        connection = sqlite3.connect(self.user_db)
        connection.row_factory = _row_factory
        try:
            yield connection
        finally:
            connection.close()

    def patches(self):
        return (
            patch.object(folders, "get_data_db", self.data_connection),
            patch.object(folders, "get_user_db", self.user_connection),
            patch.object(folders, "DATA_ROOT", self.data_root),
            patch.object(folders, "SIDECAR_DIR", self.sidecars),
            patch.object(folders, "active_tool_id", return_value=None),
        )

    def database_count(self, table: str) -> int:
        connection = sqlite3.connect(self.data_db)
        try:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            connection.close()

    def run_with_patches(self, action):
        first, second, third, fourth, fifth = self.patches()
        with first, second, third, fourth, fifth:
            return action()

    def test_preview_and_unindex_keep_every_sidecar_and_external_file(self) -> None:
        expected_sidecars = (self.canonical_json, self.canonical_tags, self.legacy)
        expected_bytes = sum(path.stat().st_size for path in expected_sidecars)
        preview = self.run_with_patches(
            lambda: folders.folder_removal_preview("external-library")
        )
        self.assertEqual(preview.indexed_files, 1)
        self.assertEqual(preview.sidecar_files, 3)
        self.assertEqual(preview.sidecar_bytes, expected_bytes)
        self.assertEqual(preview.external_images_affected, 0)
        self.assertTrue(preview.sidecar_history_preserved)

        result = self.run_with_patches(
            lambda: folders.remove_folder("external-library", "unindex_only")
        )
        self.assertEqual(result.files_removed, 1)
        self.assertEqual(result.sidecar_files_removed, 0)
        for path in (*expected_sidecars, self.media, self.adjacent, self.history, self.other_root):
            self.assertTrue(path.is_file(), f"un-index must preserve {path}")
        for table in ("files", "posts", "post_tags", "tags", "sync_manifest", "ingest_state"):
            self.assertEqual(self.database_count(table), 0, table)
        connection = sqlite3.connect(self.user_db)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM registered_folders").fetchone()[0], 0)
        finally:
            connection.close()

    def test_delete_sidecars_removes_only_current_central_metadata(self) -> None:
        expected_sidecars = (self.canonical_json, self.canonical_tags, self.legacy)
        expected_bytes = sum(path.stat().st_size for path in expected_sidecars)
        result = self.run_with_patches(
            lambda: folders.remove_folder("external-library", "delete_sidecars")
        )
        self.assertEqual(result.files_removed, 1)
        self.assertEqual(result.sidecar_files_removed, 3)
        self.assertEqual(result.sidecar_bytes_removed, expected_bytes)
        for path in expected_sidecars:
            self.assertFalse(path.exists(), f"current central sidecar should be deleted: {path}")
        for path in (self.media, self.adjacent, self.history, self.other_root):
            self.assertTrue(path.is_file(), f"removal must preserve {path}")
        self.assertEqual(self.database_count("files"), 0)


if __name__ == "__main__":
    unittest.main()
