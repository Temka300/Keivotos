from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SidebarGripContractTests(unittest.TestCase):
    def test_draggable_auto_hiding_grip_remains_the_primary_sidebar_control(self) -> None:
        source = (ROOT / "frontend" / "src" / "components" / "SidebarDock.svelte").read_text(encoding="utf-8")

        required_fragments = [
            "class:is-open={$sidebarOpen && introReady}",
            "requestAnimationFrame(",
            "class=\"sidebar-panel flex h-full overflow-hidden\"",
            ".sidebar-dock.is-open .sidebar-panel",
            "transition: width 280ms",
            "transition: transform 280ms",
            "sidebarHandlePosition.set",
            "sidebarOpen.update",
            "on:pointerdown={startGripDrag}",
            "on:pointermove={moveGrip}",
            "on:click={toggleSidebar}",
            "data-sidebar-grip-hotspot",
            "class:is-revealed={gripRevealed}",
            ".sidebar-grip-hotspot:hover .sidebar-grip-visual",
            "opacity: 0",
            "opacity: 1",
        ]
        for fragment in required_fragments:
            self.assertIn(fragment, source)

        self.assertNotIn("transition:slide", source)
        self.assertEqual(source.count("<Sidebar />"), 1)

    def test_browse_and_tags_mount_the_sidebar_dock(self) -> None:
        source = (ROOT / "frontend" / "src" / "App.svelte").read_text(encoding="utf-8")
        self.assertIn("$viewMode === 'gallery' || $viewMode === 'tags'", source)
        self.assertIn("<SidebarDock />", source)


if __name__ == "__main__":
    unittest.main()
