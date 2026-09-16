"""Characterize combo keys, upserts and shared blacklist normalization."""
from contextlib import nullcontext
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException
from modules.danbooru.models import FavoriteTagComboCreate
from modules.danbooru.routers import user_library as router
from modules.danbooru import user_library as helpers


class FavoriteTagComboTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript("""
            CREATE TABLE favorite_tag_combos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                tag_key TEXT NOT NULL UNIQUE, tags_json TEXT NOT NULL,
                added_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE blacklist_tags (tag_name TEXT PRIMARY KEY);
        """)
        override = patch.object(router, "get_user_db", side_effect=lambda: nullcontext(self.conn))
        override.start()
        self.addCleanup(override.stop)

    def test_normalization_preserves_first_order_and_unicode(self):
        tags = helpers.normalize_combo_tags([" Blue Hair ", "ALICE", "blue\thair", " ", "猫", "猫"])
        self.assertEqual(tags, ["blue_hair", "alice", "猫"])
        self.assertEqual(helpers.combo_key(tags), "alice\nblue_hair\n猫")
        self.assertEqual(helpers.combo_key(list(reversed(tags))), helpers.combo_key(tags))
        self.assertEqual(helpers.combo_name(None, tags + ["four", "five"]), "blue hair + alice + 猫 + four")
        self.assertEqual(helpers.combo_name("  Custom  ", tags), "Custom")

    def test_upsert_keeps_id_and_timestamp_but_updates_name_and_order(self):
        first = router.create_favorite_tag_combo(FavoriteTagComboCreate(tags=["Blue Hair", "Alice"]))
        self.conn.execute("UPDATE favorite_tag_combos SET added_at='2026-01-01' WHERE id=?", (first.id,))
        updated = router.create_favorite_tag_combo(FavoriteTagComboCreate(
            name=" Renamed ", tags=["alice", "BLUE HAIR", "alice"],
        ))
        self.assertEqual(updated.model_dump(), {
            "id": first.id, "name": "Renamed", "tags": ["alice", "blue_hair"], "added_at": "2026-01-01",
        })
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM favorite_tag_combos").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT tag_key FROM favorite_tag_combos").fetchone()[0],
                         "alice\nblue_hair")

    def test_rejects_less_than_two_distinct_nonempty_tags(self):
        for tags in ([], [" "], ["Alice", " ALICE "]):
            with self.subTest(tags=tags), self.assertRaises(HTTPException) as caught:
                router.create_favorite_tag_combo(FavoriteTagComboCreate(tags=tags))
            self.assertEqual(caught.exception.status_code, 400)
            self.assertEqual(caught.exception.detail, "A tag combo needs at least two tags")
        self.assertEqual(router.list_favorite_tag_combos(), [])

    def test_list_order_and_delete_preserve_other_combinations(self):
        first = router.create_favorite_tag_combo(FavoriteTagComboCreate(tags=["a", "b"]))
        second = router.create_favorite_tag_combo(FavoriteTagComboCreate(tags=["c", "d"]))
        self.conn.execute("UPDATE favorite_tag_combos SET added_at='2020-01-01' WHERE id=?", (first.id,))
        self.assertEqual([x.id for x in router.list_favorite_tag_combos()], [second.id, first.id])
        self.assertEqual(router.delete_favorite_tag_combo(first.id), {"status": "deleted", "id": first.id})
        self.assertEqual([x.id for x in router.list_favorite_tag_combos()], [second.id])

    def test_blacklist_uses_same_normalization_and_alias_identity(self):
        self.assertEqual(router.add_blacklist_tag(" Blue Hair "), {"status": "added", "name": "blue_hair"})
        self.assertEqual(router.add_blacklist_tag("BLUE\tHAIR"), {"status": "exists", "name": "blue_hair"})
        router.remove_blacklist_tag(" BLUE HAIR ")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM blacklist_tags").fetchone()[0], 0)
        for name in ("normalize_tag_name", "normalize_combo_tags", "combo_key", "combo_name", "combo_from_row"):
            self.assertIs(getattr(router, "_" + name), getattr(helpers, name))


if __name__ == "__main__":
    unittest.main()
