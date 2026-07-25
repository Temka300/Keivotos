from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402
import thumbnails  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class FilesThumbnailRouteTests(unittest.TestCase):
    """The base's thumbnail endpoint: containment, fallbacks, and cache keys."""

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-thumbs"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.suite_home = self.temp / "suite"
        self.suite_home.mkdir(parents=True)
        self.thumb_dir = self.temp / "thumbs"
        self.library = self.temp / "library"
        (self.library / "Anime").mkdir(parents=True)
        Image.new("RGB", (64, 48), "red").save(self.library / "Anime" / "cover.png")
        (self.library / "model.zip").write_bytes(b"not-an-image")

        import database
        from routers import files

        self.files = files
        # thumbnails.py binds THUMB_DIR at import, so patching config alone
        # would leak real cache writes into the user's metadata directory.
        self._patchers = [
            patch.object(config, "SUITE_HOME", self.suite_home),
            patch.object(config, "FILES_DB_PATH", self.suite_home / "base" / "files.sqlite"),
            patch.object(database, "USER_DB_PATH", self.temp / "user.sqlite"),
            patch.object(thumbnails, "THUMB_DIR", self.thumb_dir),
        ]
        for patcher in self._patchers:
            patcher.start()
        self.source = files.register_source(
            files.SourceRegister(path=str(self.library), display_name="Lib")
        )

    def tearDown(self) -> None:
        for patcher in self._patchers:
            patcher.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    def _sid(self) -> str:
        return self.source.source_id

    def _thumbnail(self, path: str, size: int = 300, **kwargs):
        # Direct calls are the project convention (no TestClient), so ``size``
        # is passed explicitly: an unresolved ``Query`` default is not an int.
        # The declared default is covered by the OpenAPI snapshot instead.
        return self.files.serve_file_thumbnail(
            source_id=self._sid(), path=path, size=size, **kwargs
        )

    def test_image_yields_a_cached_webp(self) -> None:
        response = self._thumbnail("Anime/cover.png")
        self.assertEqual(response.media_type, "image/webp")
        produced = Path(response.path)
        self.assertTrue(produced.is_file())
        self.assertEqual(produced.suffix, ".webp")
        self.assertEqual(produced.parent, self.thumb_dir)

    def test_response_is_immutably_cacheable(self) -> None:
        response = self._thumbnail("Anime/cover.png")
        self.assertIn("immutable", response.headers["cache-control"])

    def test_second_request_reuses_the_cached_file(self) -> None:
        first = Path(self._thumbnail("Anime/cover.png").path)
        stamp = first.stat().st_mtime_ns
        second = Path(self._thumbnail("Anime/cover.png").path)
        self.assertEqual(first, second)
        self.assertEqual(second.stat().st_mtime_ns, stamp)

    def test_unrenderable_type_is_404_not_a_placeholder(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self._thumbnail("model.zip")
        self.assertEqual(caught.exception.status_code, 404)

    def test_directory_is_404(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self._thumbnail("Anime")
        self.assertEqual(caught.exception.status_code, 404)

    def test_missing_file_is_404(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self._thumbnail("Anime/gone.png")
        self.assertEqual(caught.exception.status_code, 404)

    def test_traversal_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self._thumbnail("../suite/secret.png")
        self.assertEqual(caught.exception.status_code, 400)

    def test_absolute_path_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self._thumbnail("C:\\Windows\\win.ini")
        self.assertEqual(caught.exception.status_code, 400)

    def test_unknown_source_is_404(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self.files.serve_file_thumbnail(
                source_id="nope", path="Anime/cover.png", size=300
            )
        self.assertEqual(caught.exception.status_code, 404)

    def test_suite_tree_is_denied(self) -> None:
        # A source overlapping Keivotos's own tree must still refuse to render it.
        with patch.object(self.files, "_forbidden_source_paths", lambda: [self.library]):
            with self.assertRaises(HTTPException) as caught:
                self._thumbnail("Anime/cover.png")
        self.assertEqual(caught.exception.status_code, 403)


class ThumbnailCacheKeyTests(unittest.TestCase):
    """The key decides both dedup and staleness, so it gets its own coverage."""

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-thumbkey"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        self.target = self.temp / "cover.png"
        Image.new("RGB", (8, 8), "blue").save(self.target)
        from routers import files

        self.files = files

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_indexed_content_hash_wins(self) -> None:
        digest = "a" * 32
        with patch.object(self.files, "_indexed_hash", lambda _p: digest):
            self.assertEqual(self.files._thumbnail_cache_key(self.target), digest)

    def test_unhashed_file_gets_a_32_hex_key_without_reading_it(self) -> None:
        with patch.object(self.files, "_indexed_hash", lambda _p: None):
            with patch.object(
                self.files.hashlib, "md5", wraps=self.files.hashlib.md5
            ) as spy:
                key = self.files._thumbnail_cache_key(self.target)
        self.assertEqual(len(key), 32)
        int(key, 16)  # hex, or this raises
        # One cheap hash of the identity seed - never a pass over the bytes.
        self.assertEqual(spy.call_count, 1)

    def test_key_changes_when_the_file_changes(self) -> None:
        with patch.object(self.files, "_indexed_hash", lambda _p: None):
            before = self.files._thumbnail_cache_key(self.target)
            Image.new("RGB", (32, 32), "green").save(self.target)
            after = self.files._thumbnail_cache_key(self.target)
        self.assertNotEqual(before, after)

    def test_vanished_file_has_no_key(self) -> None:
        with patch.object(self.files, "_indexed_hash", lambda _p: None):
            self.assertIsNone(self.files._thumbnail_cache_key(self.temp / "gone.png"))


if __name__ == "__main__":
    unittest.main()
