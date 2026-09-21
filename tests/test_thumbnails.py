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
import config  # noqa: E402
from modules.danbooru.routers import images_media  # noqa: E402


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
        m4v = self.root / "sample.m4v"
        m4v.write_bytes(video.read_bytes())
        self.assertIsNotNone(thumbnails.ensure_thumbnail(str(m4v), 300, content_md5))

    def _make_flac(self, name: str, *, cover: bool) -> Path:
        import imageio_ffmpeg

        track = self.root / name
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        ]
        if cover:
            cover_png = self.root / "cover.png"
            Image.new("RGB", (64, 64), "orange").save(cover_png)
            command += [
                "-i", str(cover_png), "-map", "0:a", "-map", "1:v",
                "-c:a", "flac", "-c:v", "copy", "-disposition:v", "attached_pic",
            ]
        else:
            command += ["-c:a", "flac"]
        command += ["-t", "0.2", "-y", str(track)]
        subprocess.run(command, check=True, timeout=30)
        return track

    def test_flac_uses_embedded_cover_art(self) -> None:
        track = self._make_flac("track.flac", cover=True)
        content_md5 = hashlib.md5(track.read_bytes()).hexdigest()
        result = thumbnails.ensure_thumbnail(str(track), 300, content_md5)
        self.assertIsNotNone(result)
        self.assertTrue(result.exists())
        with Image.open(result) as image:
            self.assertEqual(image.format, "WEBP")

    def test_audio_without_cover_art_returns_none(self) -> None:
        track = self._make_flac("silent.flac", cover=False)
        content_md5 = hashlib.md5(track.read_bytes()).hexdigest()
        self.assertIsNone(thumbnails.ensure_thumbnail(str(track), 300, content_md5))

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


class ThumbnailCacheMigrationTests(unittest.TestCase):
    """The one-time copy of the pre-v1.1.3 cache into the current location."""

    def setUp(self) -> None:
        self.root = ROOT / "tests" / ".tmp-thumb-migration"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self._saved = {
            "THUMB_DIR": config.THUMB_DIR,
            "METADATA_DIR": config.METADATA_DIR,
            "LEGACY_DEFAULT_METADATA_DIR": config.LEGACY_DEFAULT_METADATA_DIR,
            "save_config": config.save_config,
            "cfg": dict(config._cfg),
        }
        self.metadata = self.root / "metadata_dir"
        self.old = self.metadata / "thumbnails"      # the abandoned cache
        self.new = self.root / "base" / "thumbnails"  # the current THUMB_DIR
        self.old.mkdir(parents=True, exist_ok=True)
        self.new.mkdir(parents=True, exist_ok=True)
        (self.old / "aaa_v4.webp").write_bytes(b"old-a")
        (self.old / "bbb_v4_600.webp").write_bytes(b"old-b")
        (self.new / "aaa_v4.webp").write_bytes(b"already-here")  # must survive
        config.THUMB_DIR = self.new
        config.METADATA_DIR = self.metadata
        config.LEGACY_DEFAULT_METADATA_DIR = self.root / "legacy_metadata"  # absent
        config._cfg = {}
        config.save_config = lambda overrides: config._cfg.update(overrides)

    def tearDown(self) -> None:
        config.THUMB_DIR = self._saved["THUMB_DIR"]
        config.METADATA_DIR = self._saved["METADATA_DIR"]
        config.LEGACY_DEFAULT_METADATA_DIR = self._saved["LEGACY_DEFAULT_METADATA_DIR"]
        config.save_config = self._saved["save_config"]
        config._cfg = self._saved["cfg"]
        shutil.rmtree(self.root, ignore_errors=True)

    def test_copies_missing_preserves_existing_and_runs_once(self) -> None:
        result = config.migrate_legacy_thumbnail_cache()
        self.assertTrue(result["migrated"])
        self.assertEqual(result["copied"], 1)  # only bbb; aaa already present

        # Missing key copied; the pre-existing newer entry left untouched.
        self.assertEqual((self.new / "bbb_v4_600.webp").read_bytes(), b"old-b")
        self.assertEqual((self.new / "aaa_v4.webp").read_bytes(), b"already-here")
        # Source preserved (never moved/deleted).
        self.assertTrue((self.old / "aaa_v4.webp").exists())
        self.assertTrue((self.old / "bbb_v4_600.webp").exists())

        # Flag set → a second run is a no-op.
        self.assertTrue(config._cfg.get("thumbnail_cache_migrated"))
        second = config.migrate_legacy_thumbnail_cache()
        self.assertFalse(second["migrated"])
        self.assertEqual(second["copied"], 0)
