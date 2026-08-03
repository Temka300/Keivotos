from __future__ import annotations

import shutil
import sqlite3
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from files_base import sources  # noqa: E402
from services.default_library import install_default_library  # noqa: E402


class DefaultLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-default-library"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        self.library = self.temp / "library"
        self.user_conn = sqlite3.connect(":memory:")
        self.user_conn.row_factory = sqlite3.Row
        sources.ensure_sources_schema(self.user_conn)

    def tearDown(self) -> None:
        self.user_conn.close()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_first_run_creates_folder_and_registers_visible_source(self) -> None:
        source = install_default_library(self.user_conn, self.library, forbidden_paths=[])
        self.assertIsNotNone(source)
        assert source is not None
        self.assertTrue(self.library.is_dir())
        self.assertEqual(source.role, "files")
        self.assertTrue(source.visible)
        registered = sources.list_sources(self.user_conn)
        self.assertEqual(len(registered), 1)
        self.assertEqual(
            Path(registered[0].path), self.library.resolve()
        )

    def test_existing_library_is_never_given_a_default(self) -> None:
        other = self.temp / "already-here"
        other.mkdir()
        sources.register_source(self.user_conn, str(other), "Mine")

        source = install_default_library(self.user_conn, self.library, forbidden_paths=[])
        self.assertIsNone(source)
        # The default folder was not even created, and no second source appeared.
        self.assertFalse(self.library.exists())
        self.assertEqual(len(sources.list_sources(self.user_conn)), 1)

    def test_removed_default_is_not_recreated_while_other_sources_remain(self) -> None:
        first = install_default_library(self.user_conn, self.library, forbidden_paths=[])
        assert first is not None
        # A second call with the source still registered is an idempotent no-op.
        again = install_default_library(self.user_conn, self.library, forbidden_paths=[])
        self.assertIsNone(again)
        self.assertEqual(len(sources.list_sources(self.user_conn)), 1)

    def test_unsafe_target_is_refused(self) -> None:
        # A target inside a forbidden path (e.g. Keivotos's own tree) is refused.
        source = install_default_library(
            self.user_conn, self.temp / "library", forbidden_paths=[self.temp]
        )
        self.assertIsNone(source)
        self.assertEqual(len(sources.list_sources(self.user_conn)), 0)


if __name__ == "__main__":
    unittest.main()
