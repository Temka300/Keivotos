from __future__ import annotations

import shutil
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch


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

    def test_non_folder_module_rejected_before_registering(self) -> None:
        descriptor = replace(config.MODULE_REGISTRY.require('youtube'), adopt_hook=None)
        with patch.object(folder_roles.MODULE_REGISTRY, 'get', return_value=descriptor), self.assertRaises(folder_roles.FolderRegistryError) as caught:
            folder_roles._validate_role('youtube', {'youtube'})
        self.assertEqual(caught.exception.status_code, 400)
        with database.get_user_db() as connection:
            self.assertEqual(sources.list_sources(connection), [])

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
        update = Mock(side_effect=AssertionError("Disabled hook must not run"))
        registry = config.MODULE_REGISTRY.replacing(replace(
            descriptor,
            folder_update_hook=update,
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

    def test_disabled_owner_operations_reject_before_any_batch_mutation(self) -> None:
        with database.get_user_db() as connection:
            source = sources.register_source(connection, self.library, "Library", role="danbooru")
        operations = [
            lambda: folder_roles.rescan(source.source_id),
            lambda: folder_roles.relocate(source.source_id, str(self.temp / "moved")),
            lambda: folder_roles.forget_preview(source.source_id),
            lambda: folder_roles.apply_changes([
                folder_roles.FolderChange(source.source_id, source.path, "Changed", "files")]),
            lambda: folder_roles.apply_changes([
                folder_roles.FolderChange(source.source_id, source.path, "Changed", "danbooru", forget=True)]),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaises(folder_roles.FolderRegistryError) as caught:
                operation()
            self.assertEqual(caught.exception.status_code, 409)
            with database.get_user_db() as connection:
                unchanged = sources.get_source(connection, source.source_id)
                self.assertEqual(unchanged.display_name, "Library")
                self.assertEqual(unchanged.role, "danbooru")
        self.assertFalse(self.files_db.exists())
        self.assertTrue((self.library / "one.txt").exists())

    def test_absent_owner_presentation_is_shared_but_operations_are_rejected(self) -> None:
        from module_registry import ModuleRegistry
        with database.get_user_db() as connection:
            source = sources.register_source(connection, self.library, "Library", role="danbooru")
        registry = ModuleRegistry((config.MODULE_REGISTRY.require("files"),))
        with patch.object(folder_roles, "MODULE_REGISTRY", registry), patch.object(suite_modules, "MODULE_REGISTRY", registry):
            changed = folder_roles.apply_changes([
                folder_roles.FolderChange(source.source_id, source.path, "Kept", "danbooru", visible=False)])
            self.assertEqual(changed["sources"][0].display_name, "Kept")
            with self.assertRaises(folder_roles.FolderRegistryError) as caught:
                folder_roles.rescan(source.source_id)
            self.assertEqual(caught.exception.status_code, 409)

    def test_republication_keeps_shared_label_and_synchronizes_owner_label(self) -> None:
        from modules.danbooru import publish_sources
        with database.get_user_db() as connection:
            connection.execute("CREATE TABLE registered_folders(path TEXT, display_name TEXT)")
            connection.execute("INSERT INTO registered_folders VALUES (?, ?)", (str(self.library), "Old"))
            source = sources.register_source(connection, self.library, "Shared label", role="danbooru")
            sources.update_source(connection, source.source_id, visible=False)
            publish_sources(connection)
            self.assertEqual(connection.execute("SELECT display_name FROM registered_folders").fetchone()["display_name"], "Shared label")
            shared = sources.get_source(connection, source.source_id)
            self.assertEqual(shared.display_name, "Shared label")
            self.assertFalse(shared.visible)

    def test_failed_owner_cannot_receive_new_assignment(self) -> None:
        import lifecycle
        with database.get_user_db() as connection:
            suite_modules.set_enabled(connection, "danbooru", True)
        runtime = Mock()
        runtime.status.return_value = {"state": "failed", "error": "fixture"}
        with patch.object(lifecycle, "module_runtime", runtime):
            with self.assertRaises(folder_roles.FolderRegistryError) as caught:
                folder_roles.apply_changes([
                    folder_roles.FolderChange(None, str(self.library), "Library", "danbooru")])
            self.assertEqual(caught.exception.status_code, 503)
        with database.get_user_db() as connection:
            self.assertEqual(sources.list_sources(connection), [])

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

    def test_rescan_files_source_refreshes_the_base_index(self) -> None:
        added = folder_roles.apply_changes([
            folder_roles.FolderChange(None, str(self.library), "Library", "files")
        ])
        source = added["sources"][0]
        result = folder_roles.rescan(source.source_id)
        self.assertEqual(result["source_id"], source.source_id)
        # A base (Files) folder has no extra module rescan.
        self.assertEqual(result["module"], {})
        with index.open_index(self.files_db) as connection:
            self.assertEqual(index.source_entry_count(connection, source.source_id), 1)

    def test_rescan_unknown_source_raises_not_found(self) -> None:
        with self.assertRaises(folder_roles.FolderRegistryError) as caught:
            folder_roles.rescan("does-not-exist")
        self.assertEqual(caught.exception.status_code, 404)

    def test_relocate_rejects_a_files_folder(self) -> None:
        added = folder_roles.apply_changes([
            folder_roles.FolderChange(None, str(self.library), "Library", "files")
        ])
        source = added["sources"][0]
        with self.assertRaises(folder_roles.FolderRegistryError) as caught:
            folder_roles.relocate(source.source_id, str(self.temp / "elsewhere"))
        self.assertEqual(caught.exception.status_code, 400)

    def test_relocate_dispatches_to_module_and_reindexes_at_new_path(self) -> None:
        with database.get_user_db() as connection:
            suite_modules.set_enabled(connection, "danbooru", True)
        with database.get_user_db() as connection:
            source = sources.register_source(connection, self.library, "Library", role="danbooru")
        with index.open_index(self.files_db) as index_connection:
            index.scan_source(index_connection, source.source_id, self.library, excluded_roots=[])

        moved_dir = self.temp / "moved-library"
        shutil.move(str(self.library), str(moved_dir))

        def fake_module_relocate(source_id: str, new_path: str) -> dict:
            # Stand in for the Danbooru relocate + re-publish: the module keeps its
            # own stable identity and re-points the shared source at the new path.
            with database.get_user_db() as connection:
                sources.ensure_sources_schema(connection)
                sources.remove_source(connection, source_id)
                sources.register_source(connection, new_path, "Library", role="danbooru")
            return {"files_updated": 7}

        danbooru = config.MODULE_REGISTRY.require("danbooru")
        registry = config.MODULE_REGISTRY.replacing(replace(
            danbooru,
            relocate_hook=fake_module_relocate,
            publish_hook=lambda connection: None,
        ))
        with patch.object(folder_roles, "MODULE_REGISTRY", registry):
            result = folder_roles.relocate(source.source_id, str(moved_dir))

        new_id = sources.deterministic_source_id(moved_dir)
        self.assertEqual(result["source_id"], new_id)
        self.assertEqual(result["files_updated"], 7)
        with index.open_index(self.files_db) as index_connection:
            self.assertEqual(index.source_entry_count(index_connection, source.source_id), 0)
            self.assertEqual(index.source_entry_count(index_connection, new_id), 1)

    def test_rescan_dispatches_to_the_owning_module_hook(self) -> None:
        with database.get_user_db() as connection:
            suite_modules.set_enabled(connection, "danbooru", True)
        calls: list[str] = []
        with database.get_user_db() as connection:
            source = sources.register_source(connection, self.library, "Library", role="danbooru")
        danbooru = config.MODULE_REGISTRY.require("danbooru")
        registry = config.MODULE_REGISTRY.replacing(replace(
            danbooru,
            rescan_hook=lambda source_id: (calls.append(source_id), {"status": "started"})[-1],
        ))
        with patch.object(folder_roles, "MODULE_REGISTRY", registry):
            result = folder_roles.rescan(source.source_id)
        # The module's own rescan ran, and the base index was refreshed too.
        self.assertEqual(calls, [source.source_id])
        self.assertEqual(result["module"], {"status": "started"})
        with index.open_index(self.files_db) as connection:
            self.assertEqual(index.source_entry_count(connection, source.source_id), 1)


if __name__ == "__main__":
    unittest.main()
