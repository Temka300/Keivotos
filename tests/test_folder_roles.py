from __future__ import annotations

import shutil
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import config  # noqa: E402
import database  # noqa: E402
import suite_modules  # noqa: E402
from files_base import index, sources  # noqa: E402
from services import folder_roles  # noqa: E402


class FolderRoleServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / ".tmp-folder-roles"
        shutil.rmtree(self.temp, ignore_errors=True)
        self.temp.mkdir(parents=True)
        self.library = self.temp / "library"
        self.library.mkdir()
        (self.library / "one.txt").write_text("one", encoding="utf-8")
        self.user_db = self.temp / "user.sqlite"
        self.files_db = self.temp / "files.sqlite"
        self.patchers = [
            patch.object(database, "USER_DB_PATH", self.user_db),
            patch.object(folder_roles, "FILES_DB_PATH", self.files_db),
            patch.object(folder_roles, "SUITE_HOME", self.temp / "suite"),
        ]
        for patcher in self.patchers:
            patcher.start()
        with database.get_user_db() as connection:
            sources.ensure_sources_schema(connection)
            suite_modules.ensure_schema(connection)

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_add_rename_hide_preview_and_forget_preserve_originals(self) -> None:
        added = folder_roles.apply_changes([
            folder_roles.FolderChange(
                source_id=None,
                path=str(self.library),
                display_name="Library",
                role="files",
            )
        ])
        source = added["sources"][0]
        preview = folder_roles.forget_preview(source.source_id)
        self.assertEqual(preview["base_files"], 1)

        changed = folder_roles.apply_changes([
            folder_roles.FolderChange(
                source_id=source.source_id,
                path=source.path,
                display_name="Private library",
                role="files",
                visible=False,
            )
        ])
        self.assertEqual(changed["sources"][0].display_name, "Private library")
        self.assertFalse(changed["sources"][0].visible)

        forgotten = folder_roles.apply_changes([
            folder_roles.FolderChange(
                source_id=source.source_id,
                path=source.path,
                display_name="Private library",
                role="files",
                visible=False,
                forget=True,
            )
        ])
        self.assertEqual(forgotten["sources"], [])
        self.assertTrue((self.library / "one.txt").is_file())
        with index.open_index(self.files_db) as connection:
            self.assertEqual(index.source_entry_count(connection, source.source_id), 0)

    def test_disabled_module_role_is_rejected_before_mutation(self) -> None:
        with self.assertRaises(folder_roles.FolderRegistryError) as caught:
            folder_roles.apply_changes([
                folder_roles.FolderChange(
                    source_id=None,
                    path=str(self.library),
                    display_name="Library",
                    role="danbooru",
                )
            ])
        self.assertEqual(caught.exception.status_code, 409)
        with database.get_user_db() as connection:
            self.assertEqual(sources.list_sources(connection), [])

    def test_existing_disabled_module_folder_allows_presentation_edits(self) -> None:
        with database.get_user_db() as connection:
            source = sources.register_source(connection, self.library, "Library", role="danbooru")
        descriptor = config.MODULE_REGISTRY.require("danbooru")
        registry = config.MODULE_REGISTRY.replacing(replace(
            descriptor,
            folder_update_hook=lambda source_id: None,
        ))
        with patch.object(folder_roles, "MODULE_REGISTRY", registry):
            changed = folder_roles.apply_changes([
                folder_roles.FolderChange(
                    source.source_id,
                    source.path,
                    "Hidden module folder",
                    "danbooru",
                    visible=False,
                )
            ])
        self.assertEqual(changed["sources"][0].display_name, "Hidden module folder")
        self.assertFalse(changed["sources"][0].visible)

    def test_role_changes_dispatch_through_descriptor_hooks(self) -> None:
        events: list[tuple[str, str]] = []

        def set_role(source_id: str, role: str) -> None:
            with database.get_user_db() as connection:
                sources.ensure_sources_schema(connection)
                sources.update_source(connection, source_id, role=role)

        danbooru = config.MODULE_REGISTRY.require("danbooru")
        test_registry = config.MODULE_REGISTRY.replacing(replace(
            danbooru,
            adopt_hook=lambda source_id: (events.append(("adopt", source_id)), set_role(source_id, "danbooru"), {})[-1],
            release_hook=lambda source_id, forget=False: (events.append(("release", source_id)), set_role(source_id, "files"), {})[-1],
            folder_update_hook=lambda source_id: None,
        ))
        with database.get_user_db() as connection:
            suite_modules.set_enabled(connection, "danbooru", True)

        with patch.object(folder_roles, "MODULE_REGISTRY", test_registry):
            result = folder_roles.apply_changes([
                folder_roles.FolderChange(None, str(self.library), "Library", "danbooru")
            ])
            source = result["sources"][0]
            self.assertEqual(source.role, "danbooru")
            folder_roles.apply_changes([
                folder_roles.FolderChange(source.source_id, source.path, "Library", "files")
            ])

        self.assertEqual([event[0] for event in events], ["adopt", "release"])

    def test_forgetting_nested_source_returns_ownership_to_parent(self) -> None:
        child = self.library / "child"
        child.mkdir()
        nested_file = child / "nested.txt"
        nested_file.write_text("nested", encoding="utf-8")

        parent_result = folder_roles.apply_changes([
            folder_roles.FolderChange(None, str(self.library), "Library", "files")
        ])
        parent = parent_result["sources"][0]
        nested_result = folder_roles.apply_changes([
            folder_roles.FolderChange(
                parent.source_id,
                parent.path,
                parent.display_name,
                parent.role,
            ),
            folder_roles.FolderChange(None, str(child), "Child", "files"),
        ])
        nested = next(source for source in nested_result["sources"] if source.path == str(child))

        with index.open_index(self.files_db) as connection:
            owner = connection.execute(
                "SELECT source_id FROM files_index WHERE path=?",
                (str(nested_file),),
            ).fetchone()
            self.assertEqual(owner["source_id"], nested.source_id)

        folder_roles.apply_changes([
            folder_roles.FolderChange(
                parent.source_id,
                parent.path,
                parent.display_name,
                parent.role,
            ),
            folder_roles.FolderChange(
                nested.source_id,
                nested.path,
                nested.display_name,
                nested.role,
                forget=True,
            ),
        ])

        with index.open_index(self.files_db) as connection:
            owner = connection.execute(
                "SELECT source_id FROM files_index WHERE path=?",
                (str(nested_file),),
            ).fetchone()
            self.assertEqual(owner["source_id"], parent.source_id)
        self.assertTrue(nested_file.is_file())


if __name__ == "__main__":
    unittest.main()
