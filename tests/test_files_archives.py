from __future__ import annotations

import shutil
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from files_base import archives  # noqa: E402


class ArchiveListingTests(unittest.TestCase):
    """Reading a zip's table of contents, never its contents."""

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-archives"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)

        self.zip_path = self.temp / "model.zip"
        with zipfile.ZipFile(self.zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("readme.txt", "hello" * 100)
            archive.writestr("textures/body.png", b"\x89PNG" + b"0" * 500)
            archive.writestr("empty/", "")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_lists_every_member_with_sizes(self) -> None:
        listing = archives.list_archive(self.zip_path)
        names = [entry.name for entry in listing.entries]
        self.assertIn("readme.txt", names)
        self.assertIn("textures/body.png", names)
        self.assertEqual(listing.total_entries, 3)
        self.assertFalse(listing.truncated)
        self.assertEqual(listing.total_size, 500 + 504)
        self.assertLess(listing.compressed_size, listing.total_size)

    def test_directory_members_are_marked(self) -> None:
        listing = archives.list_archive(self.zip_path)
        folder = next(e for e in listing.entries if e.name == "empty/")
        self.assertTrue(folder.is_dir)

    def test_a_non_archive_is_refused_by_content_not_extension(self) -> None:
        liar = self.temp / "not-really.zip"
        liar.write_bytes(b"this is plain text, not a zip")
        with self.assertRaises(archives.ArchiveUnreadable) as caught:
            archives.list_archive(liar)
        self.assertEqual(caught.exception.status_code, 415)

    def test_an_archive_without_a_zip_extension_still_lists(self) -> None:
        renamed = self.temp / "model.cbz"
        shutil.copy(self.zip_path, renamed)
        self.assertEqual(archives.list_archive(renamed).total_entries, 3)

    def test_entry_count_is_capped_and_reported(self) -> None:
        many = self.temp / "many.zip"
        with zipfile.ZipFile(many, "w") as archive:
            for index in range(30):
                archive.writestr(f"f{index}.txt", "x")
        listing = archives.list_archive(many, limit=10)
        self.assertEqual(len(listing.entries), 10)
        self.assertEqual(listing.total_entries, 30)
        self.assertTrue(listing.truncated)

    def test_a_hostile_member_name_is_returned_as_inert_text(self) -> None:
        hostile = self.temp / "hostile.zip"
        with zipfile.ZipFile(hostile, "w") as archive:
            archive.writestr("../../etc/passwd", "nope")
            archive.writestr("C:/Windows/win.ini", "nope")
        names = [entry.name for entry in archives.list_archive(hostile).entries]
        # Reported verbatim for display; the module never joins them to a path.
        self.assertIn("../../etc/passwd", names)
        self.assertIn("C:/Windows/win.ini", names)

    def test_nothing_is_decompressed(self) -> None:
        # The guarantee that makes a zip bomb harmless: no member is ever read.
        with patch.object(zipfile.ZipFile, "read") as read, \
             patch.object(zipfile.ZipFile, "open") as opened, \
             patch.object(zipfile.ZipFile, "extract") as extract, \
             patch.object(zipfile.ZipFile, "extractall") as extractall:
            archives.list_archive(self.zip_path)
        read.assert_not_called()
        opened.assert_not_called()
        extract.assert_not_called()
        extractall.assert_not_called()


class ArchiveRouteTests(unittest.TestCase):
    """The endpoint reuses the standard containment chain."""

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-archroute"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.suite_home = self.temp / "suite"
        self.suite_home.mkdir(parents=True)
        self.library = self.temp / "library"
        self.library.mkdir(parents=True)
        with zipfile.ZipFile(self.library / "pack.zip", "w") as archive:
            archive.writestr("a.txt", "a")
        (self.library / "notes.txt").write_bytes(b"plain")
        (self.library / "sub").mkdir()

        import database
        from routers import files

        self.files = files
        self._patchers = [
            patch.object(config, "SUITE_HOME", self.suite_home),
            patch.object(config, "FILES_DB_PATH", self.suite_home / "base" / "files.sqlite"),
            patch.object(database, "USER_DB_PATH", self.temp / "user.sqlite"),
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

    def _list(self, path: str):
        return self.files.list_archive(source_id=self.source.source_id, path=path)

    def test_lists_a_registered_archive(self) -> None:
        result = self._list("pack.zip")
        self.assertEqual(result.total_entries, 1)
        self.assertEqual(result.entries[0].name, "a.txt")

    def test_a_plain_file_is_415(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self._list("notes.txt")
        self.assertEqual(caught.exception.status_code, 415)

    def test_a_directory_is_404(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self._list("sub")
        self.assertEqual(caught.exception.status_code, 404)

    def test_traversal_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self._list("../suite/secret.zip")
        self.assertEqual(caught.exception.status_code, 400)

    def test_unknown_source_is_404(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self.files.list_archive(source_id="nope", path="pack.zip")
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
