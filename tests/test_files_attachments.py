from __future__ import annotations

import asyncio
import shutil
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402
from files_base import attachment_store, index  # noqa: E402


# A 1x1 PNG so image_dimensions has something real to read.
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c62f8cfc0f01f0005000180ff9d2c3e0000000049454e44ae426082"
)


class FakeRequest:
    def __init__(self, headers: dict[str, str], body: bytes) -> None:
        self.headers = headers
        self._body = body

    async def body(self) -> bytes:
        return self._body


def run(coro):
    return asyncio.run(coro)


class AttachmentLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-attach"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.suite_home = self.temp / "suite"
        self.suite_home.mkdir(parents=True)
        self.library = self.temp / "library"
        (self.library / "3D").mkdir(parents=True)
        (self.library / "3D" / "model.zip").write_bytes(b"a-zip-payload")

        import database
        from routers import files

        self.files = files
        self._patchers = [
            patch.object(config, "SUITE_HOME", self.suite_home),
            patch.object(config, "BASE_HOME", self.suite_home / "base"),
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

    def _upload(self, path: str, data: bytes, ctype: str, name: str):
        request = FakeRequest({"content-type": ctype, "content-length": str(len(data))}, data)
        return run(
            self.files.upload_attachment(
                request, source_id=self.source.source_id, path=path, file_name=name, caption="shot"
            )
        )

    def test_upload_stores_inside_the_first_files_folder(self) -> None:
        note = self._upload("3D/model.zip", _PNG_1x1, "image/png", "render.png")
        self.assertEqual(len(note.attachments), 1)
        attachment = note.attachments[0]
        self.assertEqual(attachment.media_type, "image/png")
        self.assertEqual(attachment.width, 1)
        self.assertEqual(attachment.height, 1)
        # Bytes live under the registered library, in the hidden store.
        stored = attachment_store.attachment_path(
            self.library, attachment.content_hash, "png"
        )
        self.assertTrue(stored.is_file())
        self.assertIn(".keivotos", stored.parts)

    def test_identical_uploads_are_deduplicated_on_disk(self) -> None:
        first = self._upload("3D/model.zip", _PNG_1x1, "image/png", "a.png")
        second = self._upload("3D/model.zip", _PNG_1x1, "image/png", "b.png")
        # Two rows, one file on disk (same content hash).
        self.assertEqual(len(second.attachments), 2)
        hashes = {a.content_hash for a in second.attachments}
        self.assertEqual(len(hashes), 1)
        del first

    def test_serve_streams_the_bytes(self) -> None:
        note = self._upload("3D/model.zip", _PNG_1x1, "image/png", "render.png")
        attachment_id = note.attachments[0].id
        response = self.files.serve_attachment(
            attachment_id, FakeRequest({}, b"")
        )
        self.assertEqual(response.media_type, "image/png")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_delete_removes_bytes_only_when_last_reference_goes(self) -> None:
        note = self._upload("3D/model.zip", _PNG_1x1, "image/png", "a.png")
        self._upload("3D/model.zip", _PNG_1x1, "image/png", "b.png")
        content_hash = note.attachments[0].id
        # Delete the first row; the shared file must survive.
        first_id = note.attachments[0].id
        self.files.delete_attachment(first_id)
        stored = attachment_store.attachment_path(
            self.library, note.attachments[0].content_hash, "png"
        )
        self.assertTrue(stored.is_file())  # still referenced by the second row
        # Delete the remaining row; now the file is gone.
        remaining = self.files.get_info(source_id=self.source.source_id, path="3D/model.zip")
        self.files.delete_attachment(remaining.attachments[0].id)
        self.assertFalse(stored.is_file())
        del content_hash

    def test_deleting_last_attachment_prunes_an_otherwise_empty_note(self) -> None:
        note = self._upload("3D/model.zip", _PNG_1x1, "image/png", "only.png")
        self.assertIsNotNone(self.files.get_info(source_id=self.source.source_id, path="3D/model.zip"))
        self.files.delete_attachment(note.attachments[0].id)
        # No description, no links, no attachments left -> the note is pruned.
        self.assertIsNone(self.files.get_info(source_id=self.source.source_id, path="3D/model.zip"))
        self.assertEqual(self.files.annotated_paths(source_id=self.source.source_id), [])

    def test_non_media_upload_is_rejected(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            self._upload("3D/model.zip", b"not media", "application/zip", "x.zip")
        self.assertEqual(caught.exception.status_code, 400)


class AttachmentScanExclusionTests(unittest.TestCase):
    def test_keivotos_store_dir_is_never_indexed(self) -> None:
        temp = ROOT / "tests" / ".tmp-attach-scan"
        shutil.rmtree(temp, ignore_errors=True)
        library = temp / "lib"
        (library / "photos").mkdir(parents=True)
        (library / "photos" / "a.png").write_bytes(b"x")
        # A planted attachment store must be invisible to the browse index.
        store = attachment_store.attachment_root(library) / "ab"
        store.mkdir(parents=True)
        (store / "abcd.png").write_bytes(b"secret-attachment")
        try:
            with index.open_index(temp / "files.sqlite") as connection:
                index.scan_source(connection, "src", library)
                top = [e.name for e in index.list_directory(connection, "src", "")]
                self.assertIn("photos", top)
                self.assertNotIn(".keivotos", top)
                everything = connection.execute(
                    "SELECT COUNT(*) FROM files_index WHERE name = 'abcd.png'"
                ).fetchone()[0]
                self.assertEqual(everything, 0)
        finally:
            shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
