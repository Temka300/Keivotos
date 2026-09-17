"""Preserve fresh/legacy index initialization and its existing normalization."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import database
from modules.danbooru import schema, index_migrations


class DanbooruIndexMigrationTests(unittest.TestCase):
    def test_dispatch_preserves_configured_path_and_connection_factory(self):
        with patch.object(index_migrations, "initialize_index") as initialize:
            database.init_data_db()
            initialize.assert_called_once_with(database.DATA_DB_PATH, database.get_data_db)

    def test_pipeline_and_backend_share_schema_functions(self):
        from scripts import danbooru_gallery_dl

        self.assertIs(danbooru_gallery_dl.ensure_data_schema, schema.ensure_data_schema)
        self.assertIs(danbooru_gallery_dl.create_data_indexes, schema.create_data_indexes)
        self.assertIs(index_migrations.ensure_data_schema, schema.ensure_data_schema)

    def test_fresh_schema_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(database, "DATA_DB_PATH", Path(temp) / "nested/index.sqlite"):
            database.init_data_db()
            with database.get_data_db() as conn:
                before = list(conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name"))
            database.init_data_db()
            with database.get_data_db() as conn:
                self.assertEqual(list(conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name")), before)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone(), {"integrity_check": "ok"})

    def test_legacy_index_preserves_rows_and_backfills_only_existing_candidates(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(database, "DATA_DB_PATH", Path(temp) / "index.sqlite"):
            path = database.DATA_DB_PATH
            with sqlite3.connect(path) as conn:
                # The legacy files table lacks root identity and download-date columns.
                conn.execute("CREATE TABLE files(id INTEGER PRIMARY KEY,path TEXT UNIQUE,folder TEXT,name TEXT,ext TEXT,size INTEGER,local_md5 TEXT,matched_md5 TEXT,matched_by TEXT)")
                schema.ensure_data_schema(conn)
                conn.executemany("INSERT INTO files(id,path,name,downloaded_at) VALUES(?,?,?,?)", [
                    (1,"/fixture/missing.jpg","missing.jpg",None),
                    (2,"/fixture/local.jpg","local.jpg","2026-01-01T10:00:00"),
                    (3,"/fixture/utc.jpg","utc.jpg","2026-01-01T00:00:00Z"),
                ])
                conn.executemany("INSERT INTO posts(id,file_id,rating,score) VALUES(?,?,?,?)",[(1,1,None,10),(2,2,"g",20),(3,3,"",30)])
            with patch.object(index_migrations, "local_downloaded_at", side_effect=lambda path: "2026-01-02T09:00:00" if path.endswith("utc.jpg") else None) as dates:
                database.init_data_db()
            self.assertEqual({call.args[0] for call in dates.call_args_list}, {"/fixture/missing.jpg", "/fixture/utc.jpg"})
            with database.get_data_db() as conn:
                self.assertEqual(list(conn.execute("SELECT id,rating,score FROM posts ORDER BY id")),
                                 [{"id":1,"rating":"u","score":10},{"id":2,"rating":"g","score":20},{"id":3,"rating":"u","score":30}])
                self.assertEqual([row["downloaded_at"] for row in conn.execute("SELECT downloaded_at FROM files ORDER BY id")],
                                 [None,"2026-01-01T10:00:00","2026-01-02T09:00:00"])
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
