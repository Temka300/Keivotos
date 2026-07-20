from __future__ import annotations

import hashlib
import shutil
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import thumbnails  # noqa: E402
import database  # noqa: E402
from routers import images_media  # noqa: E402


class ThumbnailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "tests" / ".tmp-thumbnails"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.original_thumb_dir = thumbnails.THUMB_DIR
        thumbnails.THUMB_DIR = self.root / "cache"

    def tearDown(self) -> None:
        thumbnails.THUMB_DIR = self.original_thumb_dir
        shutil.rmtree(self.root, ignore_errors=True)

    def test_content_key_survives_file_move(self) -> None:
        source = self.root / "source.png"
        moved = self.root / "moved.png"
        Image.new("RGB", (80, 40), "purple").save(source)
        content_md5 = hashlib.md5(source.read_bytes()).hexdigest()
        first = thumbnails.ensure_thumbnail(str(source), 300, content_md5)
        source.replace(moved)
        second = thumbnails.ensure_thumbnail(str(moved), 300, content_md5)
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertTrue(second.exists())

    def test_three_tiers_and_cleanup_remove_legacy_only(self) -> None:
        source = self.root / "tiers.png"
        Image.new("RGB", (1600, 900), "green").save(source)
        content_md5 = hashlib.md5(source.read_bytes()).hexdigest()
        generated = [
            thumbnails.ensure_thumbnail(str(source), requested, content_md5)
            for requested in (120, 500, 900)
        ]
        self.assertEqual(
            [path.name for path in generated if path],
            [
                f"{content_md5}_v4.webp",
                f"{content_md5}_v4_600.webp",
                f"{content_md5}_v4_1200.webp",
            ],
        )
        legacy = thumbnails.THUMB_DIR / f"{content_md5}_v3.webp"
        legacy.write_bytes(b"legacy")
        cleaned = thumbnails.cleanup_thumbnail_cache({content_md5})
        self.assertEqual(cleaned["removed"], 1)
        self.assertEqual(cleaned["tiers"], {"300": 1, "600": 1, "1200": 1})

    def test_mp4_uses_extracted_frame(self) -> None:
        import imageio_ffmpeg

        video = self.root / "sample.mp4"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=red:s=64x64:d=0.5",
                "-c:v", "mpeg4", "-y", str(video),
            ],
            check=True,
            timeout=30,
        )
        content_md5 = hashlib.md5(video.read_bytes()).hexdigest()
        result = thumbnails.ensure_thumbnail(str(video), 300, content_md5)
        self.assertIsNotNone(result)
        self.assertTrue(result.exists())
        with Image.open(result) as image:
            self.assertEqual(image.format, "WEBP")

    def test_thumbnail_endpoint_selects_and_uses_local_md5(self) -> None:
        source = self.root / "endpoint.png"
        Image.new("RGB", (80, 40), "blue").save(source)
        content_md5 = hashlib.md5(source.read_bytes()).hexdigest()
        data_db = self.root / "danbooru.sqlite"
        with closing(sqlite3.connect(data_db)) as connection:
            connection.execute(
                "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT NOT NULL, local_md5 TEXT)"
            )
            connection.execute(
                "INSERT INTO files (id, path, local_md5) VALUES (1, ?, ?)",
                (str(source), content_md5),
            )
            connection.commit()

        original_data_db = database.DATA_DB_PATH
        database.DATA_DB_PATH = data_db
        try:
            response = images_media.serve_thumbnail(1, 300)
        finally:
            database.DATA_DB_PATH = original_data_db

        self.assertEqual(response.media_type, "image/webp")
        self.assertIn(content_md5, Path(response.path).name)
        self.assertEqual(response.headers["cache-control"], "public, max-age=31536000, immutable")

    def test_thumbnail_key_locks_stay_bounded(self) -> None:
        locks = {
            id(thumbnails._thumbnail_lock(self.root / f"{index}.webp"))
            for index in range(10_000)
        }

        self.assertLessEqual(len(locks), 64)
        self.assertEqual(len(thumbnails._key_locks), 64)
