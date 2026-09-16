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
from modules.danbooru import tag_history  # noqa: E402


class TagHistoryTests(unittest.TestCase):
    def test_callers_share_history_functions(self) -> None:
        from routers import images_media, tools

        self.assertIs(images_media.removed_tags_for_file, tag_history.removed_tags_for_file)
        self.assertIs(tools.record_removed_tags_from_archive, tag_history.record_removed_tags_from_archive)

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

        archive_bytes = archived_sidecar.read_bytes()
        # An index rebuild may assign a new ID; the preserved path/hash still match.
        with database.get_data_db() as conn:
            conn.execute("UPDATE files SET id=70")
            conn.commit()
        tag_history.record_removed_tags_from_archive(archive_dir)
        with database.get_user_db() as conn:
            rows = conn.execute("SELECT * FROM tag_removals").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["file_id"], 70)

        # Existing behavior represents the latest refresh, not cumulative history.
        current_sidecar.write_bytes(archive_bytes)
        summary = tag_history.record_removed_tags_from_archive(archive_dir)
        self.assertIn("1 cleared", summary)
        with database.get_user_db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM tag_removals").fetchone()["n"], 0)
        self.assertEqual(archived_sidecar.read_bytes(), archive_bytes)
        self.assertEqual(media.read_bytes(), b"fixture")

    def test_payload_tag_forms_and_all_list_precedence(self) -> None:
        for payload, expected in (
            ({}, set()), ({"tags": "invalid"}, set()),
            ({"tags": {"all": [], "general": ["ignored"]}}, set()),
            ({"tags": {"all": ["猫", "猫", None, "", 5]}}, {"猫", "5"}),
            ({"tags": {"artist": ["alice"], "general": ["blue"], "count": 2}}, {"alice", "blue"}),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(tag_history._payload_tags(payload), expected)

    def test_missing_and_malformed_sidecars_are_skipped_without_changes(self) -> None:
        archive = self.temp / "archive"
        archive.mkdir()
        (archive / "bad.danbooru.json").write_text("{invalid", encoding="utf-8")
        (archive / "missing.danbooru.json").write_text(json.dumps({
            "local_file": {"path": str(self.data_root / "missing.jpg")},
            "tags": {"all": ["old"]},
        }), encoding="utf-8")
        originals = {p: p.read_bytes() for p in archive.iterdir()}
        self.assertEqual(tag_history.record_removed_tags_from_archive(archive),
                         "Tag history: 0 image(s) with removed upstream tags, 0 cleared, 2 skipped")
        self.assertEqual({p: p.read_bytes() for p in archive.iterdir()}, originals)
        self.assertEqual(tag_history.record_removed_tags_from_archive(self.temp / "absent"),
                         "Tag history: 0 image(s) with removed upstream tags, 0 cleared, 0 skipped")

    def test_lookup_uses_latest_matching_identity_and_tolerates_bad_values(self) -> None:
        with database.get_user_db() as conn:
            conn.execute("INSERT INTO tag_removals(file_id,file_path,local_md5,removed_tags_json,checked_at) "
                         "VALUES(7,'/old.jpg','hash','[\"old\"]','2026-01-01')")
            conn.execute("INSERT INTO tag_removals(file_id,file_path,local_md5,removed_tags_json,checked_at) "
                         "VALUES(70,'/new.jpg','hash','[\"猫\",\"blue\",\"blue\",null]','2026-02-01')")
            identity = {"file_id": 7, "path": "/old.jpg", "local_md5": "hash"}
            self.assertEqual(tag_history.removed_tags_for_file(conn, identity), ["blue", "猫"])
            for invalid in ("{invalid", '{"tag":"value"}'):
                conn.execute("UPDATE tag_removals SET removed_tags_json=?", (invalid,))
                self.assertEqual(tag_history.removed_tags_for_file(conn, identity), [])
            self.assertEqual(tag_history.removed_tags_for_file(conn, {}), [])


if __name__ == "__main__":
    unittest.main()
