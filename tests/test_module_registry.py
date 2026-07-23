from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from module_registry import build_registry  # noqa: E402


class ModuleRegistryTests(unittest.TestCase):
    def test_static_registry_has_one_required_base_and_danbooru_module(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as temporary:
            home = Path(temporary)
            registry = build_registry(home, "1.1.0")

        files = registry.require("files")
        danbooru = registry.require("danbooru")
        self.assertEqual(registry.base, files)
        self.assertTrue(files.is_base)
        self.assertFalse(files.disableable)
        self.assertEqual(files.database, home.resolve() / "base" / "files.sqlite")
        self.assertEqual(files.api_prefix, "/api/files")
        self.assertFalse(danbooru.is_base)
        self.assertTrue(danbooru.disableable)
        self.assertEqual(danbooru.database, home.resolve() / "modules" / "danbooru" / "danbooru.sqlite")
        self.assertEqual(danbooru.api_prefix, "/api/danbooru")
        self.assertIn("Danbooru", danbooru.user_agent)

    def test_registry_rejects_duplicate_slugs(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as temporary:
            registry = build_registry(Path(temporary), "1.1.0")
        with self.assertRaises(ValueError):
            type(registry)((registry.base, registry.base))


if __name__ == "__main__":
    unittest.main()
