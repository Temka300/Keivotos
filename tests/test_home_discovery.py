from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import core  # noqa: E402


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

        tags = core.home_tag_infos_with_covers(
            self.conn,
            [{"name": "sample_character", "category": "character", "cnt": 4}],
            "g",
        )

        self.assertEqual(len(tags), 1)
        self.assertEqual([candidate.file_id for candidate in tags[0].cover_candidates], [3, 4, 2, 1])
        self.assertEqual(tags[0].cover_file_id, 3)
        self.assertEqual(tags[0].cover_candidates[0].width, 1600)
        self.assertEqual(tags[0].cover_candidates[0].height, 900)

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
