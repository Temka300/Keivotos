from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import core  # noqa: E402


class FilenameSearchTests(unittest.TestCase):
    def test_pasted_media_filename_becomes_a_filename_filter(self) -> None:
        filename = "__akita_neru_vocaloid_and_1_more_drawn_by_roin__4091acdf2342e502bcaafd87a0f57308.png"
        included, excluded, filters = core.parse_search_terms(filename)

        self.assertEqual(included, [])
        self.assertEqual(excluded, [])
        self.assertEqual(filters["filename"], [filename])

        where_sql, params = core.build_where(included, excluded, filters)
        self.assertIn("LOWER(f.name) LIKE ?", where_sql)
        self.assertEqual(len(params), 1)
        self.assertTrue(params[0].startswith("%") and params[0].endswith("%"))
        self.assertIn(r"\_\_akita\_neru", params[0])

    def test_filename_prefix_supports_partial_and_negative_matches(self) -> None:
        included, excluded, filters = core.parse_search_terms("filename:akita_neru -file:sample")

        self.assertEqual(included, [])
        self.assertEqual(excluded, [])
        self.assertEqual(filters["filename"], ["akita_neru"])
        self.assertEqual(filters["exclude_filename"], ["sample"])

        where_sql, params = core.build_where(included, excluded, filters)
        self.assertIn("LOWER(f.name) LIKE ?", where_sql)
        self.assertIn("LOWER(f.name) NOT LIKE ?", where_sql)
        self.assertEqual(params, [r"%akita\_neru%", "%sample%"])

    def test_sidebar_rating_selection_accepts_multiple_ratings(self) -> None:
        included, excluded, filters = core.parse_search_terms("rating:g,s,q")

        self.assertEqual(included, [])
        self.assertEqual(excluded, [])
        where_sql, params = core.build_where(included, excluded, filters)

        self.assertIn("COALESCE(NULLIF(p.rating, ''), 'u') IN (?,?,?)", where_sql)
        self.assertEqual(params, ["g", "s", "q"])
        self.assertEqual(
            core.home_rating_clause("g,s,q"),
            ("AND COALESCE(NULLIF(p.rating, ''), 'u') IN (?,?,?)", ["g", "s", "q"]),
        )


if __name__ == "__main__":
    unittest.main()
