from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402
from files_base import index  # noqa: E402


class FilesInfoRouteTests(unittest.TestCase):
    """Exercise the annotation endpoints directly (project convention)."""

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-info"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.suite_home = self.temp / "suite"
        self.suite_home.mkdir(parents=True)
        self.library = self.temp / "library"
        (self.library / "3D").mkdir(parents=True)
        (self.library / "3D" / "iroha.zip").write_bytes(b"zip-bytes-here")
        (self.library / "Piano Sheets").mkdir()

        import database
        from routers import files

        self.files = files
        self.database = database
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

    def _sid(self) -> str:
        return self.source.source_id

    def test_file_note_roundtrip_and_lazy_hash(self) -> None:
        files = self.files
        saved = files.put_info(
            files.AnnotationRequest(
                source_id=self._sid(),
                path="3D/iroha.zip",
                description="Booth model, listing deleted",
                links=[
                    files.AnnotationLinkModel(
                        url="https://booth.pm/en/items/4309253", label="Booth", kind="source"
                    ),
                    files.AnnotationLinkModel(
                        url="https://forum.example/thread", label="Found here", kind="discussion"
                    ),
                ],
            )
        )
        self.assertIsNotNone(saved)
        self.assertEqual(saved.subject_kind, "file")
        self.assertIsNotNone(saved.content_hash)  # hashed on annotate
        self.assertEqual([l.kind for l in saved.links], ["source", "discussion"])

        # The lazy hash was written back to the index for duplicate detection.
        with index.open_index(config.FILES_DB_PATH) as index_conn:
            row = index_conn.execute(
                "SELECT content_hash FROM files_index WHERE name = 'iroha.zip'"
            ).fetchone()
        self.assertEqual(row["content_hash"], saved.content_hash)

        fetched = files.get_info(source_id=self._sid(), path="3D/iroha.zip")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, saved.id)
        self.assertEqual(fetched.description, "Booth model, listing deleted")

    def test_folder_note_is_keyed_by_path(self) -> None:
        files = self.files
        files.put_info(
            files.AnnotationRequest(
                source_id=self._sid(), path="Piano Sheets", description="BA arrangements", links=[]
            )
        )
        fetched = files.get_info(source_id=self._sid(), path="Piano Sheets")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.subject_kind, "dir")
        self.assertIsNone(fetched.content_hash)

    def test_non_http_links_are_rejected(self) -> None:
        from fastapi import HTTPException

        files = self.files
        with self.assertRaises(HTTPException) as caught:
            files.put_info(
                files.AnnotationRequest(
                    source_id=self._sid(),
                    path="3D/iroha.zip",
                    description="x",
                    links=[files.AnnotationLinkModel(url="javascript:alert(1)")],
                )
            )
        self.assertEqual(caught.exception.status_code, 400)

    def test_empty_note_is_not_stored_and_clears_an_existing_one(self) -> None:
        files = self.files
        files.put_info(
            files.AnnotationRequest(
                source_id=self._sid(), path="Piano Sheets", description="temp", links=[]
            )
        )
        cleared = files.put_info(
            files.AnnotationRequest(
                source_id=self._sid(), path="Piano Sheets", description="   ", links=[]
            )
        )
        self.assertIsNone(cleared)
        self.assertIsNone(files.get_info(source_id=self._sid(), path="Piano Sheets"))

    def test_delete_removes_the_note(self) -> None:
        files = self.files
        files.put_info(
            files.AnnotationRequest(
                source_id=self._sid(), path="3D/iroha.zip", description="keep then drop", links=[]
            )
        )
        result = files.delete_info(source_id=self._sid(), path="3D/iroha.zip")
        self.assertTrue(result["deleted"])
        self.assertIsNone(files.get_info(source_id=self._sid(), path="3D/iroha.zip"))

    def test_unknown_source_and_traversal_are_refused(self) -> None:
        from fastapi import HTTPException

        files = self.files
        with self.assertRaises(HTTPException) as unknown:
            files.get_info(source_id="src-nope", path="x")
        self.assertEqual(unknown.exception.status_code, 404)

        with self.assertRaises(HTTPException) as traversal:
            files.put_info(
                files.AnnotationRequest(
                    source_id=self._sid(), path="../suite/user.sqlite", description="x", links=[]
                )
            )
        self.assertEqual(traversal.exception.status_code, 400)

    def test_open_and_reveal_are_guarded_and_dispatch(self) -> None:
        from fastapi import HTTPException

        files = self.files
        with patch.object(files.os, "startfile", create=True) as startfile, patch.object(
            files.subprocess, "Popen"
        ) as popen:
            opened = files.open_file(
                files.SubjectRef(source_id=self._sid(), path="3D/iroha.zip")
            )
            revealed = files.reveal_file(
                files.SubjectRef(source_id=self._sid(), path="3D/iroha.zip")
            )
        self.assertEqual(opened["status"], "opened")
        self.assertEqual(revealed["status"], "revealed")
        # Exactly one of startfile/Popen ran for open depending on platform, and
        # reveal always dispatched; the point is the guard let a valid path through.
        self.assertTrue(startfile.called or popen.called)

        # A path outside the source is refused before any dispatch.
        with self.assertRaises(HTTPException) as caught:
            files.open_file(files.SubjectRef(source_id=self._sid(), path="../suite"))
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
