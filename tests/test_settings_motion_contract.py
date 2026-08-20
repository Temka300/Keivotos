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

    def test_sections_are_grouped_by_scope(self) -> None:
        # v1.1.3: the flat functional list became scope groups — General (whole
        # suite), Files (the base), and one group per module. The module group is
        # registry-driven so it disappears when the module is disabled.
        self.assertIn("const sectionGroups = [", self.source)
        self.assertIn("label: 'General'", self.source)
        self.assertIn("label: 'Files'", self.source)
        # The module group's label comes from the module's identity, not a literal
        # (keeps the release-layout no-hardcoded-'Danbooru' guard happy).
        self.assertIn("label: MODULE_NAME", self.source)
        self.assertIn("$enabledModules.includes(group.module)", self.source)


if __name__ == "__main__":
    unittest.main()
