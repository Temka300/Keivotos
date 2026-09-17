"""Daily Challenge behavior on a disposable in-memory Danbooru index."""
from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException
from modules.danbooru.routers import discovery
from modules.danbooru.schema import ensure_data_schema
from modules.danbooru import challenges


class DailyChallengeTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        ensure_data_schema(self.conn)
        self.conn.executemany("INSERT INTO tags(id,name,category) VALUES(?,?,?)", [
            (1, "alice", "character"), (2, "bob", "character"),
            (3, "carol", "character"), (4, "series", "copyright"),
            (5, "artist", "artist"), (6, "blue_hair", "general"),
            (7, "solo", "general"), (8, "highres", "meta"),
        ])
        for ident, rating, ext, characters in (
            (1, "g", "jpg", (1,)), (2, "e", "png", (2,)),
            (3, "g", "webp", (1, 3)), (4, "g", "MP4", (2,)),
            (5, None, "jpg", (3,)), (6, "g", "webm", (2,)),
        ):
            self.conn.execute(
                "INSERT INTO files(id,path,name,folder,ext,local_md5) VALUES(?,?,?,?,?,?)",
                (ident, f"/fixture/{ident}.{ext}", f"{ident}.{ext}", "Fixture", ext, f"hash-{ident}"),
            )
            self.conn.execute(
                "INSERT INTO posts(id,file_id,danbooru_post_id,rating,score,created_at,width,height) "
                "VALUES(?,?,?,?,?,?,?,?)", (ident, ident, 100 + ident, rating, 10, "2024-02-03", 800, 600),
            )
            self.conn.executemany("INSERT INTO post_tags VALUES(?,?)",
                                  [(ident, tag) for tag in characters])
        self.conn.executemany("INSERT INTO post_tags VALUES(1,?)", [(i,) for i in range(4, 9)])
        override = patch.object(discovery, "get_data_db", side_effect=lambda: nullcontext(self.conn))
        override.start()
        self.addCleanup(override.stop)

    def daily(self, rating="g", day=date(2026, 9, 16)):
        with patch.object(discovery, "date") as clock:
            clock.today.return_value = day
            return discovery.daily_challenge(rating=rating).model_dump(mode="json")

    def test_day_identity_options_and_clues_are_stable(self):
        result = self.daily()
        self.assertEqual(result, self.daily())
        self.assertEqual(result["image"]["id"], 1)
        self.assertEqual(result["image"]["thumbnail_token"], "hash-1")
        self.assertEqual(result["total_candidates"], 1)
        self.assertEqual(result["answer_tag"], "alice")
        self.assertEqual({x["name"]: x["count"] for x in result["options"]},
                         {"alice": 2, "bob": 2, "carol": 1})
        self.assertEqual(result["clues"], {
            "copyrights": ["series"], "artists": ["artist"], "general": ["blue_hair"],
            "meta": ["highres"], "folder": "Fixture", "rating": "g", "score": 10, "year": 2024,
        })
        self.assertNotEqual(result["challenge_id"], self.daily(day=date(2026, 9, 17))["challenge_id"])

    def test_multi_character_fallback_excludes_videos(self):
        self.conn.execute("DELETE FROM posts WHERE id=1")
        result = self.daily()
        self.assertEqual(result["image"]["id"], 3)
        self.assertEqual(result["answer_tag"], "alice")
        self.assertEqual(result["total_candidates"], 1)

    def test_rating_filter_and_unrated_candidates(self):
        self.assertEqual(self.daily("e")["image"]["id"], 2)
        self.assertEqual(self.daily("u")["image"]["id"], 5)
        for rating, count in ((None, 3), ("g,e", 2)):
            with self.subTest(rating=rating):
                self.assertEqual(self.daily(rating)["total_candidates"], count)

    def test_empty_filtered_pool_is_404(self):
        with self.assertRaises(HTTPException) as caught:
            self.daily("q")
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail, "No local character challenge candidates found")

    def test_suggestions_obey_rating_and_empty_query(self):
        self.assertEqual(discovery.challenge_character_suggestions(q=" ", rating="g", limit=12), [])
        suggestions = discovery.challenge_character_suggestions(q="ALICE", rating="g", limit=1)
        self.assertEqual([x.model_dump() for x in suggestions],
                         [{"name": "alice", "category": "character", "count": 2,
                           "favorite_added_at": None, "pinned_at": None}])
        self.assertEqual(discovery.challenge_character_suggestions(q="alice", rating="e", limit=12), [])

    def test_thumbnail_token_falls_back_when_hash_is_missing(self):
        row = dict(challenges.daily_challenge_candidate(self.conn, "g", 1, True))
        row["local_md5"] = None
        with patch.object(challenges, "thumbnail_cache_token", return_value="mtime-size") as token:
            self.assertEqual(challenges.daily_challenge_image_from_row(row).thumbnail_token, "mtime-size")
        token.assert_called_once_with(row["path"])


if __name__ == "__main__":
    unittest.main()
