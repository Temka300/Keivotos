"""Preserve Danbooru collection previews and durable identity joins."""
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from modules.danbooru import collections


class CollectionHelperTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript("""
            CREATE TABLE collections(id INTEGER PRIMARY KEY, name TEXT,
                description TEXT, created_at TEXT, pinned_at TEXT);
            CREATE TABLE collection_items(collection_id INTEGER, file_id INTEGER,
                file_path TEXT, local_md5 TEXT, added_at TEXT, pinned_at TEXT);
            ATTACH DATABASE ':memory:' AS datadb;
            CREATE TABLE datadb.files(id INTEGER PRIMARY KEY, path TEXT,
                local_md5 TEXT, name TEXT, ext TEXT);
            CREATE TABLE datadb.posts(file_id INTEGER, width INTEGER, height INTEGER);
            INSERT INTO collections VALUES(1, 'Preserved', 'Description', '2026-01-01', NULL);
            INSERT INTO collections VALUES(2, 'Empty', '', '2026-01-02', NULL);
        """)
        for ident, ext in ((1, "jpg"), (2, "gif"), (3, "mp4"), (4, "webm"), (5, "png")):
            self.conn.execute("INSERT INTO datadb.files VALUES(?,?,?,?,?)",
                              (ident, f"/fixture/{ident}.{ext}", f"hash-{ident}", f"{ident}.{ext}", ext))
            self.conn.execute("INSERT INTO datadb.posts VALUES(?,?,?)", (ident, 800, 600))
            self.conn.execute("INSERT INTO collection_items VALUES(1,?,?,?,?,?)",
                              (ident, None, None, f"2026-01-0{ident}", None))

    def test_preview_order_limit_and_animated_media(self):
        self.conn.execute("UPDATE collection_items SET pinned_at='2026-01-06' WHERE file_id=1")
        result = collections.load_collection_info(self.conn, 1)
        self.assertEqual(result.image_count, 5)
        self.assertEqual(result.preview_ids, [1, 5, 4, 3])
        self.assertEqual([p.ext for p in result.preview_items], ["jpg", "png", "webm", "mp4"])
        self.assertEqual([p.thumbnail_token for p in result.preview_items],
                         ["hash-1", "hash-5", "hash-4", "hash-3"])
        self.assertEqual(result.description, "Description")

    def test_path_and_hash_identity_survive_changed_index_ids(self):
        self.conn.execute("UPDATE collection_items SET file_id=101,file_path='/fixture/1.jpg' WHERE file_id=1")
        self.conn.execute("UPDATE collection_items SET file_id=102,local_md5='hash-2' WHERE file_id=2")
        self.conn.execute("UPDATE collection_items SET pinned_at='2026-01-07' WHERE file_id=101")
        self.conn.execute("UPDATE collection_items SET pinned_at='2026-01-06' WHERE file_id=102")
        result = collections.load_collection_info(self.conn, 1)
        self.assertEqual(result.image_count, 5)
        self.assertEqual(result.preview_ids[:2], [1, 2])
        self.assertEqual(result.preview_items[1].ext, "gif")

    def test_missing_media_keeps_membership_and_hash(self):
        self.conn.execute("INSERT INTO collection_items VALUES(1,99,NULL,'preserved-hash','2026-02-01',NULL)")
        result = collections.load_collection_info(self.conn, 1)
        self.assertEqual(result.image_count, 6)
        self.assertEqual(result.preview_ids[0], 99)
        self.assertEqual(result.preview_items[0].thumbnail_token, "preserved-hash")
        self.assertIsNone(result.preview_items[0].filename)

    def test_empty_and_unknown_collection(self):
        result = collections.load_collection_info(self.conn, 2)
        self.assertEqual(result.image_count, 0)
        self.assertEqual(result.preview_ids, [])
        self.assertEqual(result.preview_items, [])
        self.assertIsNone(collections.load_collection_info(self.conn, 999))

    def test_preview_token_fallback_and_null_id(self):
        row = dict(file_id=1, path="/fixture/1.jpg", local_md5=None,
                   filename="1.jpg", ext="jpg", width=800, height=600)
        with patch.object(collections, "thumbnail_cache_token", return_value="mtime-size") as token:
            result = collections.collection_preview_items_from_rows([dict(row, file_id=None), row])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].thumbnail_token, "mtime-size")
        token.assert_called_once_with(row["path"])


if __name__ == "__main__":
    unittest.main()
