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

from models import FolderCreate, FolderRelocate  # noqa: E402
from routers import folders  # noqa: E402
from schema import ensure_data_schema  # noqa: E402


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return dict(zip((column[0] for column in cursor.description), row))


class FolderRootIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-folder-roots"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        self.data_root = self.temp / "managed"
        self.data_root.mkdir()
        self.data_db = self.temp / "danbooru.sqlite"
        connection = sqlite3.connect(self.data_db)
        ensure_data_schema(connection)
        connection.commit()
        connection.close()

        self.user_db = self.temp / "user.sqlite"
        connection = sqlite3.connect(self.user_db)
        connection.executescript("""
            CREATE TABLE registered_folders (
                name TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                root_id TEXT NOT NULL,
                display_name TEXT
            );
            CREATE TABLE favorites (file_id INTEGER, file_path TEXT);
            CREATE TABLE collection_items (file_id INTEGER, file_path TEXT);
            CREATE TABLE user_image_tags (file_id INTEGER, file_path TEXT);
            CREATE TABLE image_views (file_id INTEGER, file_path TEXT);
            CREATE TABLE tag_removals (file_id INTEGER, file_path TEXT);
        """)
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    @contextmanager
    def data_connection(self):
        connection = sqlite3.connect(self.data_db)
        connection.row_factory = _row_factory
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

    def registered_rows(self):
        with self.user_connection() as connection:
            return connection.execute(
                """SELECT name AS registration_key,
                          COALESCE(NULLIF(display_name, ''), name) AS name,
                          path, root_id
                     FROM registered_folders"""
            ).fetchall()

    def common_patches(self):
        return (
            patch.object(folders, "get_data_db", self.data_connection),
            patch.object(folders, "get_user_db", self.user_connection),
            patch.object(folders, "registered_folder_rows", self.registered_rows),
            patch.object(folders, "DATA_ROOT", self.data_root),
            patch.object(folders, "USER_DB_PATH", self.user_db),
            patch.object(folders, "active_tool_id", return_value=None),
            patch.object(folders, "_start_folder_import", return_value={"status": "started"}),
        )

    def run_patched(self, action):
        patches = self.common_patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            return action()

    def test_same_display_name_can_be_registered_from_two_paths(self) -> None:
        first = self.temp / "drive-d" / "Images"
        second = self.temp / "drive-e" / "Images"
        first.mkdir(parents=True)
        second.mkdir(parents=True)

        result_one = self.run_patched(lambda: folders.register_folder(FolderCreate(path=str(first))))
        result_two = self.run_patched(lambda: folders.register_folder(FolderCreate(path=str(second))))

        self.assertEqual(result_one["name"], "Images")
        self.assertEqual(result_two["name"], "Images")
        self.assertNotEqual(result_one["root_id"], result_two["root_id"])
        self.assertNotEqual(result_one["selector"], result_two["selector"])
        self.assertEqual(len(self.registered_rows()), 2)

    def test_relocation_preserves_root_id_and_rewrites_references(self) -> None:
        old_root = self.temp / "old-drive" / "Images"
        new_root = self.temp / "new-drive" / "Images"
        old_media = old_root / "characters" / "sample.jpg"
        new_media = new_root / "characters" / "sample.jpg"
        old_media.parent.mkdir(parents=True)
        new_media.parent.mkdir(parents=True)
        old_media.write_bytes(b"old-location-placeholder")
        new_media.write_bytes(b"original-after-user-move")

        with self.user_connection() as connection:
            connection.execute(
                "INSERT INTO registered_folders(name, path, root_id, display_name) VALUES (?, ?, ?, ?)",
                ("root-stable", str(old_root), "root-stable", "Images"),
            )
            for table in ("favorites", "collection_items", "user_image_tags", "image_views", "tag_removals"):
                connection.execute(
                    f"INSERT INTO {table}(file_id, file_path) VALUES (1, ?)",
                    (str(old_media),),
                )
            connection.commit()

        with self.data_connection() as connection:
            connection.execute(
                """INSERT INTO files(id, path, folder, root_id, relative_path, name)
                   VALUES (1, ?, 'Images', 'root-stable', 'characters/sample.jpg', 'sample.jpg')""",
                (str(old_media),),
            )
            connection.execute("INSERT INTO sync_manifest(media_path) VALUES (?)", (str(old_media),))
            connection.execute("INSERT INTO ingest_state(media_path, root_id, relative_path) VALUES (?, 'root-stable', 'characters/sample.jpg')", (str(old_media),))
            connection.commit()

        result = self.run_patched(
            lambda: folders.relocate_folder("root-stable", FolderRelocate(path=str(new_root)))
        )

        self.assertEqual(result.root_id, "root-stable")
        self.assertEqual(result.files_updated, 1)
        self.assertEqual(Path(self.registered_rows()[0]["path"]), new_root.resolve())
        with self.data_connection() as connection:
            file_row = connection.execute("SELECT path, root_id, relative_path FROM files WHERE id=1").fetchone()
            self.assertEqual(file_row["path"], str(new_media.resolve()))
            self.assertEqual(file_row["root_id"], "root-stable")
            self.assertEqual(file_row["relative_path"], "characters/sample.jpg")
            self.assertEqual(connection.execute("SELECT media_path FROM sync_manifest").fetchone()["media_path"], str(new_media.resolve()))
            self.assertEqual(connection.execute("SELECT media_path FROM ingest_state").fetchone()["media_path"], str(new_media.resolve()))
        with self.user_connection() as connection:
            for table in ("favorites", "collection_items", "user_image_tags", "image_views", "tag_removals"):
                self.assertEqual(connection.execute(f"SELECT file_path FROM {table}").fetchone()["file_path"], str(new_media.resolve()))
        self.assertTrue(new_media.is_file())

    def test_relocation_tolerates_databases_without_incremental_state_tables(self) -> None:
        old_root = self.temp / "legacy-drive" / "Images"
        new_root = self.temp / "replacement-drive" / "Images"
        old_media = old_root / "sample.jpg"
        new_media = new_root / "sample.jpg"
        old_media.parent.mkdir(parents=True)
        new_media.parent.mkdir(parents=True)
        old_media.write_bytes(b"old")
        new_media.write_bytes(b"new")

        with self.user_connection() as connection:
            connection.execute(
                "INSERT INTO registered_folders(name, path, root_id, display_name) VALUES (?, ?, ?, ?)",
                ("legacy-root", str(old_root), "legacy-root", "Images"),
            )
            connection.commit()
        with self.data_connection() as connection:
            connection.execute(
                """INSERT INTO files(id, path, folder, root_id, relative_path, name)
                   VALUES (1, ?, 'Images', 'legacy-root', 'sample.jpg', 'sample.jpg')""",
                (str(old_media),),
            )
            connection.execute("DROP TABLE sync_manifest")
            connection.execute("DROP TABLE ingest_state")
            connection.commit()

        result = self.run_patched(
            lambda: folders.relocate_folder("legacy-root", FolderRelocate(path=str(new_root)))
        )

        self.assertEqual(result.files_updated, 1)
        with self.data_connection() as connection:
            self.assertEqual(connection.execute("SELECT path FROM files WHERE id=1").fetchone()["path"], str(new_media.resolve()))


if __name__ == "__main__":
    unittest.main()
