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

from models import ImageMoveFolder  # noqa: E402
from routers import images_media  # noqa: E402
from storage_layout import SIDECAR_SUFFIXES  # noqa: E402


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return dict(zip((column[0] for column in cursor.description), row))


class ImageFolderMoveTests(unittest.TestCase):
    """Single-image folder move must carry the file's sidecars with it.

    Regression: the sidecar loop referenced an undefined ``SIDECAR_SUFFIXES``,
    so every move raised NameError (and bulk move reported every image failed).
    """

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-image-move"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.source_dir = self.temp / "library" / "A"
        self.target_dir = self.temp / "library" / "B"
        self.sidecar_src = self.temp / "sidecars" / "A"
        self.sidecar_dst = self.temp / "sidecars" / "B"
        for directory in (self.source_dir, self.target_dir, self.sidecar_src, self.sidecar_dst):
            directory.mkdir(parents=True)

        self.media = self.source_dir / "img.jpg"
        self.media.write_bytes(b"image-bytes")
        for suffix in SIDECAR_SUFFIXES:
            (self.sidecar_src / f"img{suffix}").write_text(f"sidecar{suffix}", encoding="utf-8")

        self.data_db = self.temp / "danbooru.sqlite"
        connection = sqlite3.connect(self.data_db)
        connection.executescript(
            """
            CREATE TABLE files (
                id INTEGER PRIMARY KEY, path TEXT, folder TEXT, name TEXT, ext TEXT,
                size INTEGER, root_id TEXT, relative_path TEXT, local_md5 TEXT
            );
            CREATE TABLE posts (id INTEGER PRIMARY KEY, file_id INTEGER, raw_json TEXT);
            """
        )
        connection.execute(
            "INSERT INTO files (id, path, folder, name, ext, size, local_md5) VALUES (1, ?, 'A', 'img.jpg', 'jpg', 11, 'abc')",
            (str(self.media),),
        )
        connection.execute("INSERT INTO posts (id, file_id, raw_json) VALUES (77, 1, '{}')")
        connection.commit()
        connection.close()

        self.user_db = self.temp / "user.sqlite"
        connection = sqlite3.connect(self.user_db)
        connection.executescript(
            """
            CREATE TABLE favorites (file_id INTEGER, file_path TEXT, local_md5 TEXT);
            CREATE TABLE collection_items (file_id INTEGER, file_path TEXT, local_md5 TEXT);
            CREATE TABLE user_image_tags (file_id INTEGER, file_path TEXT, local_md5 TEXT);
            CREATE TABLE image_views (file_id INTEGER, file_path TEXT, local_md5 TEXT);
            CREATE TABLE tag_removals (file_id INTEGER, file_path TEXT, local_md5 TEXT);
            """
        )
        connection.commit()
        connection.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    @contextmanager
    def _data_connection(self):
        connection = sqlite3.connect(self.data_db)
        connection.row_factory = _row_factory
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _user_connection(self):
        connection = sqlite3.connect(self.user_db)
        connection.row_factory = _row_factory
        try:
            yield connection
        finally:
            connection.close()

    def _sidecar_candidates(self, media_path: Path, suffix: str) -> list[Path]:
        return [self.sidecar_src / f"{Path(media_path).stem}{suffix}"]

    def _central_sidecar_path(self, media_path: Path, suffix: str) -> Path:
        return self.sidecar_dst / f"{Path(media_path).stem}{suffix}"

    def _move(self):
        patches = [
            patch.object(images_media, "get_data_db", self._data_connection),
            patch.object(images_media, "get_user_db", self._user_connection),
            patch.object(images_media, "ensure_managed_path", lambda *a, **k: None),
            patch.object(images_media, "folder_target", lambda folder: (self.target_dir, "B")),
            patch.object(images_media, "sidecar_candidates", self._sidecar_candidates),
            patch.object(images_media, "central_sidecar_path", self._central_sidecar_path),
            patch.object(images_media, "rewrite_json_sidecar", lambda *a, **k: None),
            patch.object(images_media, "move_payload_text", lambda *a, **k: None),
            patch.object(images_media, "identity_for_media", lambda *a, **k: ("root-1", "B/img.jpg")),
            patch.object(images_media, "library_roots", lambda: []),
            patch.object(images_media, "DATA_ROOT", self.temp / "library"),
            patch.object(images_media, "get_image", lambda *a, **k: {"ok": True}),
        ]
        for item in patches:
            item.start()
        try:
            return images_media.move_image_folder(77, ImageMoveFolder(folder="B"))
        finally:
            for item in patches:
                item.stop()

    def test_move_carries_media_and_every_sidecar(self) -> None:
        self._move()

        moved_media = self.target_dir / "img.jpg"
        self.assertTrue(moved_media.is_file())
        self.assertFalse(self.media.exists())
        self.assertEqual(moved_media.read_bytes(), b"image-bytes")

        for suffix in SIDECAR_SUFFIXES:
            self.assertTrue(
                (self.sidecar_dst / f"img{suffix}").is_file(), f"{suffix} sidecar did not move"
            )
            self.assertFalse(
                (self.sidecar_src / f"img{suffix}").exists(), f"{suffix} sidecar left behind"
            )

        with self._data_connection() as connection:
            row = connection.execute("SELECT path, folder FROM files WHERE id=1").fetchone()
        self.assertEqual(row["path"], str(moved_media))
        self.assertEqual(row["folder"], "B")

    def test_sidecar_suffixes_is_resolvable_from_the_router(self) -> None:
        # Pins the exact regression: the name must resolve where it is used.
        self.assertEqual(images_media.SIDECAR_SUFFIXES, (".danbooru.json", ".tags.txt"))


if __name__ == "__main__":
    unittest.main()
