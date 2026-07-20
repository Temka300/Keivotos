from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "frontend" / "src" / "components"


class ViewNavigationTests(unittest.TestCase):
    def test_special_views_share_the_home_breadcrumb_control(self) -> None:
        breadcrumb = (COMPONENTS / "HomeBreadcrumbBack.svelte").read_text(encoding="utf-8")
        self.assertIn('aria-label="Back to Home"', breadcrumb)
        self.assertIn('d="M15 19l-7-7 7-7"', breadcrumb)

        expected = {
            "DailyChallengeView.svelte": 'current="Challenge"',
            "PopularityBrowser.svelte": 'current="Popularity"',
            "TimelapseBrowser.svelte": 'current="Timelapse"',
        }
        for filename, label in expected.items():
            with self.subTest(component=filename):
                source = (COMPONENTS / filename).read_text(encoding="utf-8")
                self.assertIn("HomeBreadcrumbBack", source)
                self.assertIn(label, source)
                self.assertIn("viewMode.set('home')", source)


if __name__ == "__main__":
    unittest.main()
