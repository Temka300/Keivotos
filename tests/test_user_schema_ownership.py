"""Preserve user records while separating table creation and identity migration."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import database


class UserSchemaOwnershipTests(unittest.TestCase):
    def test_suite_and_files_schema_do_not_create_danbooru_tables(self):
        from files_base.sources import ensure_sources_schema
        from files_base.annotations import ensure_annotations_schema
        from suite_modules import ensure_schema
        from user_schema import ensure_suite_user_schema

        with tempfile.TemporaryDirectory() as temp, patch.object(database, "USER_DB_PATH", Path(temp)/"user.sqlite"), patch.object(database, "DATA_DB_PATH", Path(temp)/"missing.sqlite"):
            with database.get_user_db() as conn:
                ensure_suite_user_schema(conn)
                ensure_sources_schema(conn)
                ensure_annotations_schema(conn)
                ensure_schema(conn)
                tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({"user_settings", "files_sources", "files_annotations", "suite_enabled_modules"} <= tables)
                self.assertFalse({"favorites", "registered_folders", "artist_follows", "tag_removals"} & tables)
                conn.execute("INSERT INTO user_settings(key,value) VALUES('profile_name','Files curator')")
                ensure_suite_user_schema(conn)
                self.assertEqual(conn.execute("SELECT value FROM user_settings").fetchone()["value"], "Files curator")
            self.assertFalse(database.DATA_DB_PATH.exists())

    def test_legacy_identity_backfill_preserves_records_and_existing_identity(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(database, "USER_DB_PATH", Path(temp)/"user.sqlite"), patch.object(database, "DATA_DB_PATH", Path(temp)/"index.sqlite"), patch.object(database, "DATA_ROOT", Path(temp)/"media"):
            database.init_data_db()
            with database.get_data_db() as conn:
                conn.execute("INSERT INTO files(id,path,name,local_md5) VALUES(7,'/fixture/seven.jpg','seven.jpg','hash-seven')")
                conn.commit()
            with database.get_user_db() as conn:
                conn.executescript("""
                    CREATE TABLE favorites(file_id INTEGER PRIMARY KEY,added_at TEXT NOT NULL);
                    INSERT INTO favorites VALUES(7,'2001-01-01');
                    CREATE TABLE registered_folders(name TEXT PRIMARY KEY,added_at TEXT NOT NULL);
                    INSERT INTO registered_folders VALUES('Legacy','2001-01-02');
                    CREATE TABLE user_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL);
                    INSERT INTO user_settings VALUES('profile_name','Preserved Curator','2001-01-03');
                    CREATE TABLE unrelated_module_notes(note TEXT);
                    INSERT INTO unrelated_module_notes VALUES('preserve unknown owner');
                """)
            database.init_user_db()
            with database.get_user_db() as conn:
                favorite = conn.execute("SELECT * FROM favorites").fetchone()
                self.assertEqual((favorite["file_id"],favorite["file_path"],favorite["local_md5"],favorite["added_at"]),
                                 (7,"/fixture/seven.jpg","hash-seven","2001-01-01"))
                folder = conn.execute("SELECT * FROM registered_folders").fetchone()
                self.assertEqual(folder["path"], str(Path(temp)/"media/Legacy"))
                self.assertTrue(folder["root_id"])
                self.assertEqual(folder["display_name"], "Legacy")
                conn.execute("UPDATE favorites SET file_path='/preserved.jpg',local_md5='preserved-hash'")
                conn.commit()
            database.init_user_db()
            with database.get_user_db() as conn:
                self.assertEqual(conn.execute("SELECT file_path,local_md5 FROM favorites").fetchone(),
                                 {"file_path":"/preserved.jpg","local_md5":"preserved-hash"})
                self.assertEqual(conn.execute("SELECT * FROM registered_folders").fetchone(), folder)
                self.assertEqual(conn.execute("SELECT * FROM user_settings").fetchone(),
                                 {"key":"profile_name","value":"Preserved Curator","updated_at":"2001-01-03"})
                self.assertEqual(conn.execute("SELECT note FROM unrelated_module_notes").fetchone()["note"], "preserve unknown owner")
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone(), {"integrity_check":"ok"})

    def test_missing_index_is_not_created_by_user_initialization(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(database, "USER_DB_PATH", Path(temp)/"user.sqlite"), patch.object(database, "DATA_DB_PATH", Path(temp)/"missing.sqlite"):
            database.init_user_db()
            with database.get_user_db() as conn:
                before = list(conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name"))
            database.init_user_db()
            with database.get_user_db() as conn:
                self.assertEqual(list(conn.execute("SELECT name,sql FROM sqlite_master ORDER BY name")), before)
            self.assertFalse(database.DATA_DB_PATH.exists())
