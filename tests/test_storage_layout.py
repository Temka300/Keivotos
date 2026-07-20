from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from storage_layout import (  # noqa: E402
    LibraryRoot,
    canonical_sidecar_path,
    migrate_existing_sidecars,
    root_sidecar_directory,
)


class StorageLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-storage-layout"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.library = self.temp / "external-library"
        self.sidecars = self.temp / "metadata" / "sidecars"
        self.media = self.library / "characters" / "sample.jpg"
        self.media.parent.mkdir(parents=True)
        self.media.write_bytes(b"image")
        self.root = LibraryRoot("root-stable-test", "external-library", self.library)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_registered_root_identity_survives_and_legacy_copy_is_preserved(self) -> None:
        canonical = canonical_sidecar_path(
            self.media, ".danbooru.json", self.temp / "portable", self.sidecars, [self.root]
        )
        self.assertEqual(
            canonical,
            self.sidecars / "roots" / "root-stable-test" / "characters" / "sample.jpg.danbooru.json",
        )
        legacy = self.media.with_name(self.media.name + ".danbooru.json")
        legacy.write_text("durable metadata", encoding="utf-8")
        result = migrate_existing_sidecars(
            [self.media], self.temp / "portable", self.sidecars, [self.root], [".danbooru.json"]
        )
        self.assertEqual(result["copied"], 1)
        self.assertEqual(canonical.read_text(encoding="utf-8"), "durable metadata")
        self.assertTrue(legacy.is_file(), "migration must not delete the preservation copy")

    def test_root_sidecar_directory_rejects_escape_from_metadata(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid library root identity"):
            root_sidecar_directory("..", self.sidecars)


if __name__ == "__main__":
    unittest.main()
