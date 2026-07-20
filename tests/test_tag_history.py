from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database  # noqa: E402
import tag_history  # noqa: E402


class TagHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-tag-history"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        self.data_root = self.temp / "library"
        self.sidecar_dir = self.temp / "sidecars"
        self.data_db = self.temp / "danbooru.sqlite"
        self.user_db = self.temp / "user.sqlite"
        self.originals = (
            database.DATA_DB_PATH,
            database.USER_DB_PATH,
            tag_history.DATA_ROOT,
            tag_history.SIDECAR_DIR,
        )
        database.DATA_DB_PATH = self.data_db
        database.USER_DB_PATH = self.user_db
        tag_history.DATA_ROOT = self.data_root
        tag_history.SIDECAR_DIR = self.sidecar_dir

        with closing(sqlite3.connect(self.data_db)) as conn:
            conn.execute(
                "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT NOT NULL, local_md5 TEXT)"
            )
            conn.commit()
        database.init_user_db()

    def tearDown(self) -> None:
        (
            database.DATA_DB_PATH,
            database.USER_DB_PATH,
            tag_history.DATA_ROOT,
            tag_history.SIDECAR_DIR,
        ) = self.originals
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_manual_refresh_records_removed_tags_by_durable_identity(self) -> None:
        media = self.data_root / "Folder" / "sample.jpg"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"fixture")
        local_md5 = "0123456789abcdef0123456789abcdef"
        with closing(sqlite3.connect(self.data_db)) as conn:
            conn.execute("INSERT INTO files VALUES (?, ?, ?)", (7, str(media), local_md5))
            conn.commit()

        current_sidecar = self.sidecar_dir / "Folder" / "sample.jpg.danbooru.json"
        current_sidecar.parent.mkdir(parents=True)
        current_sidecar.write_text(
            json.dumps(
                {
                    "local_file": {"path": str(media), "md5": local_md5},
                    "tags": {"all": ["kept_tag", "new_tag"]},
                }
            ),
            encoding="utf-8",
        )
        archive_dir = self.temp / "archive"
        archived_sidecar = archive_dir / "_central_sidecars" / "Folder" / current_sidecar.name
        archived_sidecar.parent.mkdir(parents=True)
        archived_sidecar.write_text(
            json.dumps(
                {
                    "local_file": {"path": str(media), "md5": local_md5},
                    "tags": {"all": ["kept_tag", "removed_tag"]},
                }
            ),
            encoding="utf-8",
        )

        summary = tag_history.record_removed_tags_from_archive(archive_dir)
        with database.get_user_db() as conn:
            removed = tag_history.removed_tags_for_file(
                conn,
                {"file_id": 7, "path": str(media), "local_md5": local_md5},
            )

        self.assertIn("1 image(s)", summary)
        self.assertEqual(removed, ["removed_tag"])


if __name__ == "__main__":
    unittest.main()
