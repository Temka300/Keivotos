from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from modules.danbooru import home  # noqa: E402


class HomeDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT, category TEXT);
            CREATE TABLE files (
                id INTEGER PRIMARY KEY,
                path TEXT,
                local_md5 TEXT,
                name TEXT,
                folder TEXT,
                ext TEXT
            );
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY,
                file_id INTEGER,
                width INTEGER,
                height INTEGER,
                score INTEGER,
                rating TEXT,
                created_at TEXT
            );
            CREATE TABLE post_tags (post_id INTEGER, tag_id INTEGER);
            INSERT INTO tags VALUES (1, 'sample_character', 'character');
            """
        )

    def tearDown(self) -> None:
        self.conn.close()

    def add_candidate(self, file_id: int, width: int, height: int, score: int) -> None:
        self.conn.execute(
            "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)",
            (file_id, f"C:/library/{file_id}.jpg", f"md5-{file_id}", f"{file_id}.jpg", "Library", "jpg"),
        )
        self.conn.execute(
            "INSERT INTO posts VALUES (?, ?, ?, ?, ?, 'g', '2026-01-01')",
            (file_id, file_id, width, height, score),
        )
        self.conn.execute("INSERT INTO post_tags VALUES (?, 1)", (file_id,))

    def test_home_candidates_prefer_landscape_before_score(self) -> None:
        self.add_candidate(1, 800, 1400, 500)
        self.add_candidate(2, 1000, 1000, 400)
        self.add_candidate(3, 1600, 900, 10)
        self.add_candidate(4, 1400, 1000, 200)

        tags = home.home_tag_infos_with_covers(
            self.conn,
            [{"name": "sample_character", "category": "character", "cnt": 4}],
            "g",
        )

        self.assertEqual(len(tags), 1)
        self.assertEqual([candidate.file_id for candidate in tags[0].cover_candidates], [3, 4, 2, 1])
        self.assertEqual(tags[0].cover_file_id, 3)
        self.assertEqual(tags[0].cover_candidates[0].width, 1600)
        self.assertEqual(tags[0].cover_candidates[0].height, 900)

    def test_cover_limit_rating_and_video_exclusion(self) -> None:
        for ident in range(1, 10):
            self.add_candidate(ident, 1600, 900, ident)
        self.conn.execute("UPDATE files SET ext='MP4' WHERE id=9")
        self.conn.execute("UPDATE posts SET rating='e' WHERE id=8")
        rows = [{"name": "sample_character", "category": "character", "cnt": 9}]
        result = home.home_tag_infos_with_covers(self.conn, rows, "g")
        self.assertEqual([x.file_id for x in result[0].cover_candidates], [7, 6, 5, 4, 3, 2])
        self.assertEqual(result[0].count, 9)
        self.assertEqual(home.home_tag_infos_with_covers(self.conn, rows, "q"), [])
        self.assertEqual(home.home_tag_infos_with_covers(self.conn, [], None), [])
        self.assertEqual(home.top_tag_rows(self.conn, "character", "e", 1)[0]["cnt"], 1)

    def test_rail_cover_rotation_and_favorite_identity(self) -> None:
        for ident in range(1, 7):
            self.add_candidate(ident, 1600, 900, ident)
        self.conn.execute("ATTACH DATABASE ':memory:' AS userdb")
        self.conn.execute("CREATE TABLE userdb.favorites(file_id INTEGER, file_path TEXT, local_md5 TEXT)")
        # Identity joins must recognize a favorite despite an obsolete file ID.
        self.conn.execute("INSERT INTO userdb.favorites VALUES(999, NULL, 'md5-4')")
        rows = [{"name": "sample_character", "category": "character", "cnt": 6}]
        covers = home.home_cover_rows_for_tags(self.conn, rows, "g")
        self.assertEqual(len(covers), 1)
        self.assertEqual(covers[0]["file_id"], 4)
        item = home.home_image_rail_item(dict(covers[0]), "sample_character", "character")
        self.assertTrue(item.is_favorite)
        self.assertEqual(item.thumbnail_token, "md5-4")
        self.assertEqual(item.tag_name, "sample_character")
        self.assertFalse(home.home_image_rail_item(dict(covers[0]), is_favorite=False).is_favorite)
        self.assertEqual(home.home_cover_rows_for_tags(self.conn, [], "g"), [])

    def test_cache_expiry_preserves_other_keys(self) -> None:
        cache = {}
        value, other = object(), object()
        with patch.object(home.time, "monotonic", return_value=10):
            self.assertIs(home.home_cache_set(cache, ("g",), value), value)
        with patch.object(home.time, "monotonic", return_value=20):
            home.home_cache_set(cache, ("e",), other)
        with patch.object(home.time, "monotonic", return_value=310):
            self.assertIs(home.home_cache_get(cache, ("g",)), value)
        with patch.object(home.time, "monotonic", return_value=311):
            self.assertIsNone(home.home_cache_get(cache, ("g",)))
            self.assertNotIn(("g",), cache)
            self.assertIs(home.home_cache_get(cache, ("e",)), other)
            self.assertIsNone(home.home_cache_get(cache, ("missing",)))

    def test_all_consumers_share_cache_instances_and_invalidation(self) -> None:
        from modules.danbooru import challenges, tools
        from modules.danbooru.routers import discovery, user_library

        self.assertIs(discovery.HOME_TAGS_CACHE, home.HOME_TAGS_CACHE)
        self.assertIs(discovery.HOME_IMAGE_RAILS_CACHE, home.HOME_IMAGE_RAILS_CACHE)
        self.assertIs(challenges.home_rating_clause, home.home_rating_clause)
        self.assertIs(tools.clear_home_caches, home.clear_home_caches)
        self.assertIs(user_library.clear_home_caches, home.clear_home_caches)
        self.addCleanup(home.clear_home_caches)
        home.home_cache_set(home.HOME_TAGS_CACHE, ("fixture",), object())
        home.home_cache_set(home.HOME_IMAGE_RAILS_CACHE, ("fixture",), object())
        user_library.clear_home_caches()
        self.assertEqual(discovery.HOME_TAGS_CACHE, {})
        self.assertEqual(discovery.HOME_IMAGE_RAILS_CACHE, {})

    def test_spotlight_source_keeps_five_item_progress_contract(self) -> None:
        source = (ROOT / "frontend" / "src" / "components" / "HomeView.svelte").read_text(encoding="utf-8")

        required_fragments = [
            "const SPOTLIGHT_DURATION_MS = 9000",
            "Math.min(5, tags.length)",
            "animate:flip={{ duration: 440 }}",
            "class:is-active={item.offset === 0}",
            "spotlight-progress-fill",
            "window.setTimeout(() => moveSpotlight(1), SPOTLIGHT_DURATION_MS)",
            "item.width / item.height < 0.9 ? '50% 24%'",
            "const unassigned = rail.items.filter((item) => !assignedIds.has(item.file_id))",
            "unassigned.length > 0 ? unassigned : rail.items",
            "items: discoveryLaneItems(rail, railIndex, assignedHomeArtworkIds)",
            "const spotlightCategories = ['character', 'copyright', 'artist', 'general']",
            "on:click={openSpotlightImage}",
            "function scheduleDailyReset()",
            "tags: dailySequence(",
            "per_rail: 24",
            "Daily spotlight · {spotlightCategoryLabels",
        ]
        for fragment in required_fragments:
            self.assertIn(fragment, source)
        self.assertNotIn("local paths</span>", source)

    def test_lane_keyboard_focus_pauses_without_sticking_after_detail(self) -> None:
        source = (ROOT / "frontend" / "src" / "components" / "HomeView.svelte").read_text(encoding="utf-8")

        self.assertIn(".home-lane:focus-within .home-lane-track", source)
        self.assertIn("activeElement.closest('.home-lane')", source)
        self.assertIn("activeElement.blur()", source)

        open_image = source.index("function openImage(item: HomeImageRailItem)")
        release_focus = source.index("releaseLaneFocusPause();", open_image)
        select_image = source.index("selectedImageId.set(item.id);", open_image)
        self.assertLess(release_focus, select_image)


if __name__ == "__main__":
    unittest.main()
