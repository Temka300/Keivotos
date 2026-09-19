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
        registry = (ROOT / "frontend/src/modules/settings.ts").read_text(encoding="utf-8")
        general = (ROOT / "frontend/src/settings/settings.ts").read_text(encoding="utf-8")
        files = (ROOT / "frontend/src/modules/files/settings.ts").read_text(encoding="utf-8")
        module = (ROOT / "frontend/src/modules/danbooru/settings.ts").read_text(encoding="utf-8")
        self.assertIn("const sectionGroups = settingsContributions.map", self.source)
        self.assertIn("label: 'General'", general)
        self.assertIn("label: 'Files'", files)
        self.assertIn("label: MODULE_NAME", module)
        self.assertIn("'./*/settings.ts'", registry)
        self.assertIn("$enabledModules.includes(group.module)", self.source)


if __name__ == "__main__":
    unittest.main()
