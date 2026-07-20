from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SettingsMotionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            ROOT / "frontend" / "src" / "components" / "AppSettingsModal.svelte"
        ).read_text(encoding="utf-8")

    def test_search_jump_restores_motion_aware_smooth_scroll(self) -> None:
        self.assertIn(
            "behavior: $motionPreference === 'reduced' ? 'auto' : 'smooth'",
            self.source,
        )
        self.assertIn("}, 1400);", self.source)
        self.assertIn("animation: setting-highlight 1.35s ease-out", self.source)

    def test_search_jump_keeps_repeated_highlight_cleanup(self) -> None:
        self.assertIn(
            "document.querySelector('.setting-flash')?.classList.remove('setting-flash')",
            self.source,
        )
        self.assertIn(
            "if (searchHighlightTimer) clearTimeout(searchHighlightTimer)",
            self.source,
        )
        self.assertIn("void target.getBoundingClientRect()", self.source)

    def test_colored_preference_summaries_have_visible_names(self) -> None:
        self.assertIn(
            'text-purple-100">Browsing</h3>',
            self.source,
        )
        self.assertIn(
            'text-pink-100">Display</h3>',
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
