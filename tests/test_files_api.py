from __future__ import annotations

import shutil
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from files_base import sources  # noqa: E402


class SourcesRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-sources"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        self.library = self.temp / "hoard"
        self.library.mkdir()
        self.conn = sqlite3.connect(self.temp / "user.sqlite")
        self.conn.row_factory = sqlite3.Row
        sources.ensure_sources_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_register_is_idempotent_by_path(self) -> None:
        first = sources.register_source(self.conn, self.library, "My Hoard")
        second = sources.register_source(self.conn, self.library)
        self.assertEqual(first.source_id, second.source_id)
        self.assertEqual(second.display_name, "My Hoard")  # not overwritten
        self.assertEqual(second.role, "files")
        self.assertTrue(second.visible)
        self.assertEqual(len(sources.list_sources(self.conn)), 1)

    def test_visibility_and_display_name_upgrade_are_additive(self) -> None:
        source = sources.register_source(self.conn, self.library)
        updated = sources.update_source(
            self.conn,
            source.source_id,
            display_name="Hidden Hoard",
            visible=False,
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.display_name, "Hidden Hoard")
        self.assertFalse(updated.visible)
        self.assertEqual(sources.list_sources(self.conn, visible_only=True), [])

    def test_legacy_base_role_is_read_as_files_without_rewriting_it(self) -> None:
        legacy = sqlite3.connect(self.temp / "legacy-user.sqlite")
        legacy.row_factory = sqlite3.Row
        legacy.execute(
            """CREATE TABLE files_sources (
                   source_id TEXT PRIMARY KEY,
                   path TEXT NOT NULL UNIQUE,
                   display_name TEXT NOT NULL,
                   role TEXT NOT NULL DEFAULT 'base',
                   added_at TEXT
               )"""
        )
        legacy.execute(
            "INSERT INTO files_sources VALUES ('legacy', ?, 'Legacy', 'base', NULL)",
            (str(self.library),),
        )
        legacy.commit()
        sources.ensure_sources_schema(legacy)
        loaded = sources.list_sources(legacy)[0]
        self.assertEqual(loaded.role, "files")
        self.assertTrue(loaded.visible)
        self.assertEqual(legacy.execute("SELECT role FROM files_sources").fetchone()[0], "base")
        legacy.close()

    def test_remove_forgets_source(self) -> None:
        source = sources.register_source(self.conn, self.library)
        self.assertTrue(sources.remove_source(self.conn, source.source_id))
        self.assertEqual(sources.list_sources(self.conn), [])
        self.assertFalse(sources.remove_source(self.conn, source.source_id))

    def test_unsafe_reason_blocks_missing_and_fenced_paths(self) -> None:
        self.assertIsNotNone(
            sources.unsafe_source_reason(self.temp / "nope", [])
        )
        # A folder inside a fenced (generated) tree is rejected.
        fenced_child = self.library
        self.assertIsNotNone(
            sources.unsafe_source_reason(fenced_child, [self.temp])
        )
        # A normal folder outside any fence is allowed.
        self.assertIsNone(
            sources.unsafe_source_reason(self.library, [self.temp / "elsewhere"])
        )


class ModuleProjectionTests(unittest.TestCase):
    """Danbooru publishes its folders into the shared browse-list (folder-roles)."""

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-module-projection"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        (self.temp / "booru-a").mkdir()
        (self.temp / "booru-b").mkdir()
        (self.temp / "plain").mkdir()
        self.conn = sqlite3.connect(self.temp / "user.sqlite")
        self.conn.row_factory = sqlite3.Row
        sources.ensure_sources_schema(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_publish_and_withdraw_a_module_folder(self) -> None:
        sources.upsert_module_source(self.conn, self.temp / "booru-a", "Booru A", "danbooru")
        listed = sources.list_sources(self.conn)
        self.assertEqual([(s.display_name, s.role) for s in listed], [("Booru A", "danbooru")])
        self.assertTrue(sources.remove_source_by_path(self.conn, self.temp / "booru-a"))
        self.assertEqual(sources.list_sources(self.conn), [])

    def test_promoting_a_base_folder_changes_its_role(self) -> None:
        sources.register_source(self.conn, self.temp / "plain")
        sources.upsert_module_source(self.conn, self.temp / "plain", None, "danbooru")
        rows = sources.list_sources(self.conn)
        self.assertEqual(len(rows), 1)  # same folder, not duplicated
        self.assertEqual(rows[0].role, "danbooru")

    def test_reconcile_matches_the_module_list_exactly(self) -> None:
        # Stale danbooru row that is no longer registered...
        sources.upsert_module_source(self.conn, self.temp / "booru-a", None, "danbooru")
        # ...a base folder that must be left untouched...
        sources.register_source(self.conn, self.temp / "plain")
        sources.reconcile_module_sources(
            self.conn, "danbooru", [(str(self.temp / "booru-b"), "Booru B")]
        )
        by_role = {s.display_name: s.role for s in sources.list_sources(self.conn)}
        self.assertEqual(by_role, {"Booru B": "danbooru", "plain": "files"})  # booru-a pruned


class FilesApiRouteTests(unittest.TestCase):
    """Exercise the router functions directly (project convention: no TestClient)."""

    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-files-api"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        self.suite_home = self.temp / "suite"
        self.suite_home.mkdir()
        self.library = self.temp / "library"
        (self.library / "sub").mkdir(parents=True)
        (self.library / "a.png").write_bytes(b"png")
        (self.library / "notes.txt").write_bytes(b"txt")
        (self.library / "sub" / "clip.mp4").write_bytes(b"mp4")

        import config
        import database
        from routers import files

        self.files = files
        self._patchers = [
            patch.object(config, "SUITE_HOME", self.suite_home),
            patch.object(config, "FILES_DB_PATH", self.suite_home / "base" / "files.sqlite"),
            patch.object(database, "USER_DB_PATH", self.temp / "user.sqlite"),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self._patchers:
            patcher.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_register_browse_search_remove_roundtrip(self) -> None:
        files = self.files
        registered = files.register_source(
            files.SourceRegister(path=str(self.library), display_name="Lib")
        )
        source_id = registered.source_id

        self.assertEqual([s.display_name for s in files.list_sources()], ["Lib"])

        top = files.browse(source_id=source_id, parent="")
        self.assertEqual(top[0].name, "sub")
        self.assertTrue(top[0].is_dir)
        names = [n.name for n in top]
        self.assertIn("a.png", names)
        self.assertIn("notes.txt", names)  # type-agnostic

        found = files.search(q="clip", source_id=None, limit=200)
        self.assertEqual([n.name for n in found], ["clip.mp4"])

        removal = files.remove_source(source_id=source_id)
        self.assertTrue(removal.removed)
        self.assertEqual(files.list_sources(), [])
        # Originals on disk are never touched by removal.
        self.assertTrue((self.library / "a.png").exists())

    def test_register_rejects_fenced_path(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            self.files.register_source(self.files.SourceRegister(path=str(self.suite_home)))
        self.assertEqual(caught.exception.status_code, 400)

    def test_unknown_source_is_404(self) -> None:
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as browse_error:
            self.files.browse(source_id="src-nope", parent="")
        self.assertEqual(browse_error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as scan_error:
            self.files.scan_source(source_id="src-nope")
        self.assertEqual(scan_error.exception.status_code, 404)

    def test_nested_source_ownership_survives_parent_rescan_and_reclaims_on_remove(self) -> None:
        files = self.files
        parent = files.register_source(files.SourceRegister(path=str(self.library)))
        child_path = self.library / "sub"
        child = files.register_source(files.SourceRegister(path=str(child_path)))

        self.assertEqual(
            [node.name for node in files.browse(source_id=parent.source_id, parent="")][0],
            "sub",
        )
        self.assertEqual(
            [node.name for node in files.browse(source_id=child.source_id, parent="")],
            ["clip.mp4"],
        )

        files.scan_source(source_id=parent.source_id)
        self.assertEqual(
            [node.name for node in files.browse(source_id=child.source_id, parent="")],
            ["clip.mp4"],
        )
        self.assertEqual(
            [node.name for node in files.search(q="clip", source_id=parent.source_id, limit=200)],
            ["clip.mp4"],
        )

        files.remove_source(source_id=child.source_id)
        self.assertEqual(
            [node.name for node in files.browse(source_id=parent.source_id, parent="sub")],
            ["clip.mp4"],
        )


if __name__ == "__main__":
    unittest.main()
