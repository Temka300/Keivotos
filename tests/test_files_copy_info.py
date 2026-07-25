from __future__ import annotations

import asyncio
import io
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from files_base import attachment_store  # noqa: E402


class CopyOriginInfoTests(unittest.TestCase):
    """Carrying a note from an archive onto what was extracted from it."""

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-copyinfo"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.suite_home = self.temp / "suite"
        self.suite_home.mkdir(parents=True)
        self.library = self.temp / "library"
        self.library.mkdir(parents=True)
        (self.library / "iroha_ver1_0.zip").write_bytes(b"the archive")
        (self.library / "iroha_ver1_0").mkdir()
        (self.library / "iroha_ver1_0" / "model.fbx").write_bytes(b"extracted")
        (self.library / "unrelated.zip").write_bytes(b"another archive")

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
        files.scan_source(self.source.source_id)

    def tearDown(self) -> None:
        for patcher in self._patchers:
            patcher.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    # --- helpers ---------------------------------------------------------

    def _sid(self) -> str:
        return self.source.source_id

    def _ref(self, path: str):
        return self.files.SubjectRef(source_id=self._sid(), path=path)

    def _write_note(self, path: str, description: str, links: list[tuple[str, str]]):
        return self.files.put_info(
            self.files.AnnotationRequest(
                source_id=self._sid(),
                path=path,
                description=description,
                links=[
                    self.files.AnnotationLinkModel(url=url, label="", kind=kind)
                    for url, kind in links
                ],
            )
        )

    def _attach(self, path: str, colour: str) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (12, 9), colour).save(buffer, format="PNG")
        payload = buffer.getvalue()

        class _Request:
            headers = {"content-type": "image/png", "content-length": str(len(payload))}

            async def body(self):
                return payload

        asyncio.run(
            self.files.upload_attachment(
                _Request(), source_id=self._sid(), path=path, file_name="shot.png", caption=""
            )
        )

    def _copy(self, src: str, dst: str, overwrite: bool = False):
        return self.files.copy_info(
            self.files.CopyInfoRequest(
                source=self._ref(src), target=self._ref(dst), overwrite_description=overwrite
            )
        )

    # --- tests -----------------------------------------------------------

    def test_description_and_links_carry_to_the_extracted_folder(self) -> None:
        self._write_note(
            "iroha_ver1_0.zip",
            "Booth model, listing deleted",
            [("https://booth.pm/en/items/4309253", "source")],
        )
        result = self._copy("iroha_ver1_0.zip", "iroha_ver1_0")
        self.assertEqual(result.description, "Booth model, listing deleted")
        self.assertEqual([link.url for link in result.links], ["https://booth.pm/en/items/4309253"])
        self.assertEqual(result.subject_kind, "dir")

    def test_the_source_note_is_left_alone(self) -> None:
        self._write_note("iroha_ver1_0.zip", "Original", [("https://a.example", "source")])
        self._copy("iroha_ver1_0.zip", "iroha_ver1_0")
        still = self.files.get_info(source_id=self._sid(), path="iroha_ver1_0.zip")
        self.assertEqual(still.description, "Original")
        self.assertEqual(len(still.links), 1)

    def test_an_existing_description_is_not_silently_replaced(self) -> None:
        self._write_note("iroha_ver1_0.zip", "From the archive", [])
        self._write_note("iroha_ver1_0", "Hand written, do not lose", [])
        with self.assertRaises(HTTPException) as caught:
            self._copy("iroha_ver1_0.zip", "iroha_ver1_0")
        self.assertEqual(caught.exception.status_code, 409)
        kept = self.files.get_info(source_id=self._sid(), path="iroha_ver1_0")
        self.assertEqual(kept.description, "Hand written, do not lose")

    def test_overwrite_is_possible_when_asked_for(self) -> None:
        self._write_note("iroha_ver1_0.zip", "From the archive", [])
        self._write_note("iroha_ver1_0", "Placeholder", [])
        result = self._copy("iroha_ver1_0.zip", "iroha_ver1_0", overwrite=True)
        self.assertEqual(result.description, "From the archive")

    def test_links_merge_as_a_union_and_repeat_copies_are_idempotent(self) -> None:
        self._write_note(
            "iroha_ver1_0.zip", "A", [("https://a.example", "source"), ("https://b.example", "mirror")]
        )
        self._write_note("iroha_ver1_0", "", [("https://b.example", "mirror")])
        first = self._copy("iroha_ver1_0.zip", "iroha_ver1_0")
        self.assertEqual(len(first.links), 2)
        second = self._copy("iroha_ver1_0.zip", "iroha_ver1_0", overwrite=True)
        self.assertEqual(len(second.links), 2)

    def test_target_only_links_survive_the_copy(self) -> None:
        self._write_note("iroha_ver1_0.zip", "A", [("https://from-zip.example", "source")])
        self._write_note("iroha_ver1_0", "", [("https://mine.example", "discussion")])
        result = self._copy("iroha_ver1_0.zip", "iroha_ver1_0")
        urls = {link.url for link in result.links}
        self.assertIn("https://mine.example", urls)
        self.assertIn("https://from-zip.example", urls)

    def test_attachments_are_shared_not_duplicated_on_disk(self) -> None:
        self._write_note("iroha_ver1_0.zip", "A", [])
        self._attach("iroha_ver1_0.zip", "red")
        store = attachment_store.attachment_root(self.library)
        before = sorted(p.name for p in store.rglob("*") if p.is_file())

        result = self._copy("iroha_ver1_0.zip", "iroha_ver1_0")
        self.assertEqual(len(result.attachments), 1)
        after = sorted(p.name for p in store.rglob("*") if p.is_file())
        self.assertEqual(before, after)  # the row is new, the bytes are not

        again = self._copy("iroha_ver1_0.zip", "iroha_ver1_0", overwrite=True)
        self.assertEqual(len(again.attachments), 1)  # no duplicate row either

    def test_copying_onto_itself_is_refused(self) -> None:
        self._write_note("iroha_ver1_0.zip", "A", [])
        with self.assertRaises(HTTPException) as caught:
            self._copy("iroha_ver1_0.zip", "iroha_ver1_0.zip")
        self.assertEqual(caught.exception.status_code, 400)

    def test_copying_from_an_unannotated_subject_is_404(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self._copy("unrelated.zip", "iroha_ver1_0")
        self.assertEqual(caught.exception.status_code, 404)

    def test_traversal_in_either_reference_is_refused(self) -> None:
        self._write_note("iroha_ver1_0.zip", "A", [])
        for src, dst in [("../outside.zip", "iroha_ver1_0"), ("iroha_ver1_0.zip", "../outside")]:
            with self.assertRaises(HTTPException) as caught:
                self._copy(src, dst)
            self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
