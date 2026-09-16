"""Characterize Danbooru's rating, tag grammar and legacy identity precedence."""
import ast
import importlib
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from modules.danbooru import query_helpers as query
from modules.danbooru import tag_names as tags


class DanbooruQueryHelperTests(unittest.TestCase):
    def test_callers_share_the_module_objects(self):
        owners = {"modules.danbooru.query_helpers": query,
                  "modules.danbooru.tag_names": tags}
        callers = set()
        for path in (ROOT / "backend").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.ImportFrom) or node.module not in owners:
                    continue
                caller_name = ".".join(path.relative_to(ROOT / "backend").with_suffix("").parts)
                caller = importlib.import_module(caller_name)
                callers.add(caller_name)
                for name in node.names:
                    self.assertIs(getattr(caller, name.asname or name.name),
                                  getattr(owners[node.module], name.name))
        self.assertEqual(callers, {
            "modules.danbooru.routers.collections", "modules.danbooru.routers.artists", "modules.danbooru.routers.tags",
            "modules.danbooru.routers.images_media", "modules.danbooru.routers.stats", "modules.danbooru.routers.discovery", "modules.danbooru.routers.user_library",
            "modules.danbooru.collections", "modules.danbooru.tags", "modules.danbooru.home",
            "modules.danbooru.image_activity", "modules.danbooru.search",
            "modules.danbooru.image_queries", "modules.danbooru.artist_profiles",
            "modules.danbooru.tag_wiki",
        })

    def test_rating_normalization_preserves_order_and_accepted_forms(self):
        for value, expected in (
            (None, []), ("", []), ("  ", []), ("Egsuqq", ["g", "s", "q", "e", "u"]),
            (" U | e + G,s q ", ["g", "s", "q", "e", "u"]),
            ("invalid,g,unknown", ["g"]), ("general", ["g", "e"]),
        ):
            with self.subTest(value=value):
                self.assertEqual(query.normalize_rating_values(value), expected)

    def test_tag_grammar_preserves_quotes_whitespace_and_categories(self):
        for value, expected in (("  'Blue\t Hair'  ", "blue_hair"),
                                ('"猫 GIRL"', "猫_girl"), ("  ", ""),
                                ("' spaced '", "_spaced_")):
            with self.subTest(value=value):
                self.assertEqual(tags.normalize_search_tag(value), expected)
                self.assertEqual(tags.normalize_user_tag(value), expected)
        self.assertIsNot(tags.normalize_search_tag, tags.normalize_user_tag)
        self.assertEqual(tags.TAG_CATEGORIES,
                         {"artist", "character", "copyright", "general", "meta", "unknown"})
        for value, expected in ((None, "general"), (" ARTIST ", "artist"),
                                ("unknown", "unknown"), ("invalid", "general")):
            with self.subTest(value=value):
                self.assertEqual(tags.normalize_user_tag_category(value), expected)

    def test_identity_join_and_lookup_agree_on_path_hash_id_precedence(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript("""
            CREATE TABLE files(id, path, local_md5);
            INSERT INTO files VALUES(7, '/current.jpg', 'hash');
            CREATE TABLE saved(label, file_id, file_path, local_md5);
        """)
        conn.executemany("INSERT INTO saved VALUES(?,?,?,?)", [
            ("path", 999, "/current.jpg", "other"),
            ("hash", 999, None, "hash"),
            ("legacy", 7, None, None),
            ("wrong-path", 7, "/other.jpg", "hash"),
            ("wrong-hash", 7, None, "other"),
            ("empty-path", 7, "", "hash"),
            ("empty-hash", 7, None, ""),
        ])
        expected = {"path", "hash", "legacy"}
        joined = conn.execute("SELECT s.label FROM files f JOIN saved s ON " + query.user_file_match("s"))
        self.assertEqual({row[0] for row in joined}, expected)
        params = query.user_file_lookup_params({"file_id": 7, "path": "/current.jpg", "local_md5": "hash"})
        self.assertEqual(params, ["/current.jpg", "hash", 7])
        for alias in ("", "s"):
            found = conn.execute("SELECT label FROM saved s WHERE " + query.user_file_lookup_sql(alias), params)
            self.assertEqual({row[0] for row in found}, expected)
        self.assertEqual(query.user_file_lookup_params({}), [None, None, None])
        conn.execute("UPDATE files SET local_md5=NULL")
        joined = conn.execute("SELECT s.label FROM files f JOIN saved s ON " + query.user_file_match("s"))
        self.assertEqual({row[0] for row in joined}, {"path", "legacy"})


if __name__ == "__main__":
    unittest.main()
