from __future__ import annotations

import io
import shutil
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import danbooru_gallery_dl as gallery  # noqa: E402
from storage_layout import LibraryRoot  # noqa: E402


class ImportPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-import-phases"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.library = self.temp / "external-library"
        self.library.mkdir(parents=True)
        self.media = self.library / "sample.png"
        Image.new("RGB", (640, 480), (120, 30, 200)).save(self.media)
        self.database = self.temp / "danbooru.sqlite"
        self.sidecars = self.temp / "sidecars"
        self.user_db = self.temp / "user.sqlite"
        self.original_roots = gallery._LIBRARY_ROOTS
        gallery._LIBRARY_ROOTS = [LibraryRoot("root-import-test", "external-library", self.library)]

    def tearDown(self) -> None:
        gallery._LIBRARY_ROOTS = self.original_roots
        shutil.rmtree(self.temp, ignore_errors=True)

    def args(self, command: str):
        values = [
            "--root", str(self.temp),
            "--sidecar-dir", str(self.sidecars),
            "--user-db", str(self.user_db),
            command,
            "--output", str(self.database),
        ]
        if command == "import-enrich":
            values.extend(["--workers", "2"])
        values.append(str(self.library))
        parsed = gallery.build_parser().parse_args(values)
        parsed.root = parsed.root.resolve()
        return parsed

    def backfill_args(self):
        values = [
            "--root", str(self.temp),
            "--sidecar-dir", str(self.sidecars),
            "--user-db", str(self.user_db),
            "backfill",
            "--use-indexed-md5",
            "--database", str(self.database),
            "--delay", "0",
            str(self.library),
        ]
        parsed = gallery.build_parser().parse_args(values)
        parsed.root = parsed.root.resolve()
        return parsed

    def prepare_enriched_file(self) -> None:
        self.assertEqual(gallery.run_import_discover(self.args("import-discover")), 0)
        self.assertEqual(gallery.run_import_enrich(self.args("import-enrich")), 0)

    def test_discover_enrich_and_finalize_are_resumable_phases(self) -> None:
        self.assertEqual(gallery.run_import_discover(self.args("import-discover")), 0)
        connection = sqlite3.connect(self.database)
        discovered = connection.execute(
            "SELECT root_id, relative_path, local_md5 FROM files"
        ).fetchone()
        connection.close()
        self.assertEqual(discovered[:2], ("root-import-test", "sample.png"))
        self.assertIsNone(discovered[2], "phase 1 must not open or hash file contents")

        self.assertEqual(gallery.run_import_enrich(self.args("import-enrich")), 0)
        connection = sqlite3.connect(self.database)
        enriched = connection.execute(
            """SELECT f.local_md5, p.width, p.height, s.enriched_at
               FROM files f JOIN posts p ON p.file_id=f.id
               JOIN ingest_state s ON s.media_path=f.path"""
        ).fetchone()
        connection.close()
        self.assertEqual(len(enriched[0]), 32)
        self.assertEqual(enriched[1:3], (640, 480))
        self.assertIsNotNone(enriched[3])

        self.assertEqual(gallery.run_import_finalize(self.args("import-finalize")), 0)
        connection = sqlite3.connect(self.database)
        finalized = connection.execute(
            "SELECT phase, status, finalized_at FROM ingest_state"
        ).fetchone()
        connection.close()
        self.assertEqual(finalized[:2], ("finalized", "done"))
        self.assertIsNotNone(finalized[2])

    def test_metadata_phase_reports_current_file_and_matched_result(self) -> None:
        self.prepare_enriched_file()
        post = {
            "id": 123,
            "rating": "g",
            "tag_string_general": "blue_archive",
            "tag_string_artist": "sample_artist",
            "tag_string_character": "sample_character",
            "tag_string_copyright": "blue_archive",
            "tag_string_meta": "",
        }
        output = io.StringIO()
        with patch.object(gallery, "find_post_by_md5", return_value=(post, "indexed_md5", "abc")):
            with redirect_stdout(output):
                self.assertEqual(gallery.run_backfill(self.backfill_args()), 0)

        text = output.getvalue()
        self.assertIn('"status": "working"', text)
        self.assertIn('"status": "matched"', text)
        self.assertIn('"filename": "sample.png"', text)
        connection = sqlite3.connect(self.database)
        state = connection.execute(
            "SELECT phase, status, error, metadata_at FROM ingest_state"
        ).fetchone()
        connection.close()
        self.assertEqual(state[:3], ("metadata", "done", None))
        self.assertIsNotNone(state[3])

    def test_metadata_phase_preserves_no_match_for_review(self) -> None:
        self.prepare_enriched_file()
        output = io.StringIO()
        with patch.object(gallery, "find_post_by_md5", return_value=(None, None, None)):
            with redirect_stdout(output):
                self.assertEqual(gallery.run_backfill(self.backfill_args()), 0)

        self.assertIn('"status": "no_match"', output.getvalue())
        connection = sqlite3.connect(self.database)
        state = connection.execute(
            "SELECT phase, status, error, metadata_at FROM ingest_state"
        ).fetchone()
        connection.close()
        self.assertEqual(state[:2], ("metadata", "no_match"))
        self.assertIn("No Danbooru MD5 match", state[2])
        self.assertIsNone(state[3])

        self.assertEqual(gallery.run_import_finalize(self.args("import-finalize")), 0)
        connection = sqlite3.connect(self.database)
        finalized = connection.execute(
            "SELECT status, error, finalized_at FROM ingest_state"
        ).fetchone()
        connection.close()
        self.assertEqual(finalized[0], "no_match")
        self.assertIn("No Danbooru MD5 match", finalized[1])
        self.assertIsNotNone(finalized[2])


if __name__ == "__main__":
    unittest.main()
