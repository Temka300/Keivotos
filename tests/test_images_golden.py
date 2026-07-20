from __future__ import annotations

import json
import sqlite3
import sys
import shutil
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database  # noqa: E402
import core  # noqa: E402
from routers import images_media  # noqa: E402


DATA_SCHEMA = """
CREATE TABLE files (
    id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, folder TEXT, name TEXT NOT NULL,
    ext TEXT, size INTEGER, local_md5 TEXT, downloaded_at TEXT, matched_md5 TEXT, matched_by TEXT
);
CREATE TABLE posts (
    id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL UNIQUE, danbooru_post_id INTEGER,
    post_url TEXT, rating TEXT, score INTEGER, source_url TEXT, created_at TEXT, updated_at TEXT,
    parent_id INTEGER, has_children INTEGER, child_ids_json TEXT, width INTEGER, height INTEGER,
    file_ext TEXT, raw_json TEXT
);
CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, category TEXT NOT NULL);
CREATE TABLE post_tags (post_id INTEGER NOT NULL, tag_id INTEGER NOT NULL, PRIMARY KEY (post_id, tag_id));
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sync_manifest (media_path TEXT PRIMARY KEY, sidecar_path TEXT, sidecar_mtime INTEGER,
    sidecar_size INTEGER, media_mtime INTEGER, media_size INTEGER, synced_at TEXT);
"""


class ImageGoldenMasterTests(unittest.TestCase):
    def setUp(self) -> None:
        root = ROOT / "tests" / ".tmp-images"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.data_db = root / "danbooru.sqlite"
        self.user_db = root / "user.sqlite"
        self.originals = (
            database.DATA_DB_PATH,
            database.USER_DB_PATH,
            core.DATA_DB_PATH,
            core.USER_DB_PATH,
            images_media.USER_DB_PATH,
        )
        database.DATA_DB_PATH = self.data_db
        database.USER_DB_PATH = self.user_db
        core.DATA_DB_PATH = self.data_db
        core.USER_DB_PATH = self.user_db
        images_media.USER_DB_PATH = self.user_db

        with closing(sqlite3.connect(self.data_db)) as connection:
            connection.executescript(DATA_SCHEMA)
            connection.executemany(
                "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
                [
                    (1, "C:/seed/general.jpg", "Seed", "general.jpg", "jpg", 100, "aaa", "2026-01-01"),
                    (2, "C:/seed/explicit.png", "Seed", "explicit.png", "png", 200, "bbb", "2026-01-02"),
                    (3, "C:/seed/unrated.webp", "Other", "unrated.webp", "webp", 300, "ccc", "2026-01-03"),
                ],
            )
            connection.executemany(
                "INSERT INTO posts VALUES (?, ?, ?, NULL, ?, ?, NULL, ?, NULL, NULL, 0, NULL, ?, ?, ?, NULL)",
                [
                    (1, 1, 101, "g", 10, "2026-02-01", 800, 1200, "jpg"),
                    (2, 2, 102, "e", 20, "2026-02-02", 1200, 800, "png"),
                    (3, 3, None, "u", None, "2026-02-03", 640, 640, "webp"),
                ],
            )
            connection.executemany("INSERT INTO tags VALUES (?, ?, ?)", [(1, "blue_hair", "general"), (2, "red_hair", "general")])
            connection.executemany("INSERT INTO post_tags VALUES (?, ?)", [(1, 1), (2, 2)])
            connection.commit()
        database.init_user_db()

    def tearDown(self) -> None:
        database.DATA_DB_PATH, database.USER_DB_PATH, core.DATA_DB_PATH, core.USER_DB_PATH, images_media.USER_DB_PATH = self.originals
        shutil.rmtree(self.root, ignore_errors=True)

    def _case(self, **kwargs):
        result = images_media.list_images(offset=0, limit=60, duplicates_only=False, duplicate_scope="all", favorites_only=False, collection_id=None, blacklist="", folder=None, **kwargs)
        return result.model_dump(mode="json")

    def test_api_images_matches_committed_golden_master(self) -> None:
        actual = {
            "all": self._case(q="", sort="id", order="asc", rating=None),
            "general": self._case(q="", sort="id", order="asc", rating="g"),
            "unrated": self._case(q="rating:u", sort="id", order="asc", rating=None),
            "negative_tag": self._case(q="-red_hair", sort="id", order="asc", rating=None),
        }
        expected = json.loads((ROOT / "tests" / "snapshots" / "images.json").read_text(encoding="utf-8"))
        self.assertEqual(actual, expected)

    def test_image_detail_includes_removed_upstream_tags(self) -> None:
        with database.get_user_db() as connection:
            connection.execute(
                """INSERT INTO tag_removals
                   (file_id, file_path, local_md5, removed_tags_json, checked_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (1, "C:/seed/general.jpg", "aaa", '["old_tag"]', "2026-07-14T00:00:00+00:00"),
            )
            connection.commit()

        detail = images_media.get_image(1, record_view=False)

        self.assertEqual(detail.removed_tags, ["old_tag"])

    def test_legacy_and_modern_favorite_rows_do_not_duplicate_grid_results(self) -> None:
        with database.get_user_db() as connection:
            connection.execute(
                "INSERT INTO favorites(file_id, file_path, local_md5) VALUES (1, ?, 'aaa')",
                ("C:/seed/general.jpg",),
            )
            connection.execute(
                "INSERT INTO favorites(file_id, file_path, local_md5) VALUES (999, NULL, 'aaa')"
            )
            connection.commit()

        result = images_media.list_images(
            q="",
            sort="date",
            order="desc",
            rating=None,
            offset=0,
            limit=60,
            duplicates_only=False,
            duplicate_scope="all",
            favorites_only=True,
            collection_id=None,
            blacklist="",
            folder=None,
        )

        self.assertEqual(result.total, 1)
        self.assertEqual([image.file_id for image in result.images], [1])

    def test_timelapse_samples_in_sql_instead_of_returning_every_match(self) -> None:
        with database.get_data_db() as connection:
            for index in range(4, 44):
                connection.execute(
                    "INSERT INTO files VALUES (?, ?, 'Seed', ?, 'jpg', 100, ?, '2026-01-01', NULL, NULL)",
                    (index, f"C:/seed/{index}.jpg", f"{index}.jpg", f"md5-{index}"),
                )
                connection.execute(
                    """INSERT INTO posts VALUES (?, ?, NULL, NULL, 'g', 1, NULL, ?, NULL, NULL, 0, NULL,
                       800, 600, 'jpg', NULL)""",
                    (index, index, f"2026-03-{1 + (index % 28):02d}T00:00:00"),
                )
            connection.commit()

        result = images_media.timelapse_frames(frame_count=12)

        self.assertEqual(result.total, 43)
        self.assertEqual(result.sampled, 12)
        self.assertEqual(len(result.images), 12)
