from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from product import DISPLAY_NAME, VERSION  # noqa: E402


@contextmanager
def isolated_home():
    path = ROOT / "tests" / f".tmp-release-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class ReleaseLayoutTests(unittest.TestCase):
    def test_checked_in_defaults_are_external_to_the_repository(self) -> None:
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["data_root"], "library")
        self.assertEqual(config["metadata_dir"], ".")
        self.assertEqual(config["gallery_dl_dir"], "gallery-dl")
        self.assertNotIn("backup_destination", config)

    def test_release_outputs_are_ignored_at_the_repository_root(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/Keivotos-V*-windows-x64/", ignore)
        self.assertIn("/Keivotos-V*-windows-x64.zip", ignore)
        self.assertIn("/Keivotos-V*-windows-x64.zip.sha256", ignore)
        self.assertIn("/download.png", ignore)

    def test_default_scan_configuration_contains_no_personal_folder_names(self) -> None:
        config_source = (ROOT / "backend" / "config.py").read_text(encoding="utf-8")
        pipeline_source = (ROOT / "scripts" / "danbooru_gallery_dl.py").read_text(encoding="utf-8")
        for personal_name in ("Danbooru_kivotos", "Danbooru_zANKI"):
            self.assertNotIn(personal_name, config_source)
            self.assertNotIn(personal_name, pipeline_source)

    def test_windows_local_app_data_known_folder_is_the_default_source(self) -> None:
        source = (ROOT / "backend" / "config.py").read_text(encoding="utf-8")
        self.assertIn("SHGetKnownFolderPath", source)
        self.assertIn("FOLDERID_LOCAL_APP_DATA", source)
        self.assertIn('local_app_data_directory() / "Keivotos"', source)

    def test_documents_suite_home_is_copied_verified_and_rebased(self) -> None:
        with isolated_home() as temporary:
            legacy = temporary / "Documents" / "Keivotos"
            destination = temporary / "LocalAppData" / "Keivotos"
            module = legacy / "modules" / "danbooru"
            (module / "sidecars").mkdir(parents=True)
            connection = sqlite3.connect(module / "user.sqlite")
            connection.execute("CREATE TABLE marker(value TEXT NOT NULL)")
            connection.execute("INSERT INTO marker(value) VALUES ('user-database')")
            connection.commit()
            connection.close()
            (module / "sidecars" / "sample.json").write_text("sidecar", encoding="utf-8")
            (legacy / "config.json").write_text(
                json.dumps({
                    "metadata_dir": str(module),
                    "gallery_dl_dir": str(module / "gallery-dl"),
                    "thumbnail_cache_limit_gb": 5,
                }),
                encoding="utf-8",
            )
            environment = {**os.environ, "KEIVOTOS_HOME": str(temporary / "isolated-import")}
            code = (
                "import json, sys; from pathlib import Path; "
                f"sys.path.insert(0, {str(ROOT / 'backend')!r}); "
                "import config; "
                f"result=config.migrate_legacy_suite_home(Path({str(legacy)!r}), Path({str(destination)!r})); "
                "print(json.dumps(result))"
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            migration = json.loads(result.stdout)
            self.assertTrue(migration["migrated"])
            self.assertTrue(migration["config_rebased"])
            for database in (destination / "modules" / "danbooru" / "user.sqlite", module / "user.sqlite"):
                connection = sqlite3.connect(database)
                value = connection.execute("SELECT value FROM marker").fetchone()[0]
                connection.close()
                self.assertEqual(value, "user-database")
            migrated_config = json.loads((destination / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(migrated_config["metadata_dir"], str(destination / "modules" / "danbooru"))
            self.assertEqual(migrated_config["thumbnail_cache_limit_gb"], 5)

    def test_previous_module_home_is_copied_verified_and_rebased(self) -> None:
        with isolated_home() as temporary:
            previous = temporary / "modules" / "retired-module"
            destination = temporary / "modules" / "danbooru"
            (previous / "sidecars").mkdir(parents=True)
            connection = sqlite3.connect(previous / "user.sqlite")
            connection.execute("CREATE TABLE marker(value TEXT NOT NULL)")
            connection.execute("INSERT INTO marker(value) VALUES ('preserved-user-database')")
            connection.commit()
            connection.close()
            (previous / "sidecars" / "sample.json").write_text("sidecar", encoding="utf-8")
            (temporary / "config.json").write_text(
                json.dumps({
                    "metadata_dir": str(previous),
                    "gallery_dl_dir": str(previous / "gallery-dl"),
                }),
                encoding="utf-8",
            )
            environment = {
                **os.environ,
                "KEIVOTOS_HOME": str(temporary),
                "KEIVOTOS_MIGRATE_LEGACY_HOME": "1",
            }
            code = (
                "import json, sys; "
                f"sys.path.insert(0, {str(ROOT / 'backend')!r}); "
                "import config; "
                "print(json.dumps(config.MODULE_HOME_MIGRATION))"
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            migration = json.loads(result.stdout)
            self.assertTrue(migration["migrated"])
            self.assertTrue(migration["config_rebased"])
            for database in (previous / "user.sqlite", destination / "user.sqlite"):
                connection = sqlite3.connect(database)
                value = connection.execute("SELECT value FROM marker").fetchone()[0]
                connection.close()
                self.assertEqual(value, "preserved-user-database")
            self.assertEqual((destination / "sidecars" / "sample.json").read_text(encoding="utf-8"), "sidecar")
            migrated_config = json.loads((temporary / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(migrated_config["metadata_dir"], str(destination))

    def test_legacy_metadata_wrapper_is_flattened_without_overwrite(self) -> None:
        with isolated_home() as temporary:
            legacy = temporary / "modules" / "danbooru" / "metadata"
            (legacy / "sidecars" / "roots").mkdir(parents=True)
            (legacy / "sidecars" / "roots" / "sample.json").write_text("sidecar", encoding="utf-8")
            (legacy / "danbooru.sqlite").write_bytes(b"library-db")
            (legacy / "user.sqlite").write_bytes(b"user-db")
            environment = {**os.environ, "KEIVOTOS_HOME": str(temporary)}
            code = (
                "import json, sys; from pathlib import Path; "
                f"sys.path.insert(0, {str(ROOT / 'backend')!r}); "
                "import config; "
                "print(json.dumps(config.migrate_legacy_default_metadata()))"
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            migration = json.loads(result.stdout)
            module_home = temporary / "modules" / "danbooru"
            self.assertTrue(migration["migrated"])
            self.assertFalse(legacy.exists())
            self.assertEqual((module_home / "danbooru.sqlite").read_bytes(), b"library-db")
            self.assertEqual((module_home / "user.sqlite").read_bytes(), b"user-db")
            self.assertEqual((module_home / "sidecars" / "roots" / "sample.json").read_text(encoding="utf-8"), "sidecar")

    def test_legacy_metadata_conflict_is_preserved(self) -> None:
        with isolated_home() as temporary:
            module_home = temporary / "modules" / "danbooru"
            legacy = module_home / "metadata"
            legacy.mkdir(parents=True)
            (module_home / "user.sqlite").write_bytes(b"new-location")
            (legacy / "user.sqlite").write_bytes(b"legacy-location")
            environment = {**os.environ, "KEIVOTOS_HOME": str(temporary)}
            code = (
                "import sys; "
                f"sys.path.insert(0, {str(ROOT / 'backend')!r}); "
                "import config; "
                "config.migrate_legacy_default_metadata()"
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("conflicting destination", result.stderr)
            self.assertEqual((module_home / "user.sqlite").read_bytes(), b"new-location")
            self.assertEqual((legacy / "user.sqlite").read_bytes(), b"legacy-location")

    def test_generated_folder_guard_allows_library_beside_metadata(self) -> None:
        with isolated_home() as temporary:
            environment = {**os.environ, "KEIVOTOS_HOME": str(temporary)}
            code = (
                "import json, sys; from pathlib import Path; "
                f"sys.path.insert(0, {str(ROOT / 'backend')!r}); "
                "import config; from routers.folders import _is_generated_folder, _unsafe_library_root_reason; "
                "p=config.MODULE_HOME; "
                "print(json.dumps({"
                "'root': _is_generated_folder(p), "
                "'library': _is_generated_folder(p/'library'/'images'), "
                "'sidecars': _is_generated_folder(p/'sidecars'/'roots'), "
                "'gallery': _is_generated_folder(p/'gallery-dl'/'work'), "
                "'suite': _is_generated_folder(config.SUITE_HOME), "
                "'backups': _is_generated_folder(config.DEFAULT_BACKUP_DIR), "
                "'logs': _is_generated_folder(config.LOG_DIR), "
                "'drive': _unsafe_library_root_reason(Path(p.anchor))"
                "}))"
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            guard = json.loads(result.stdout)
            self.assertTrue(guard["root"])
            self.assertFalse(guard["library"])
            self.assertTrue(guard["sidecars"])
            self.assertTrue(guard["gallery"])
            self.assertTrue(guard["suite"])
            self.assertTrue(guard["backups"])
            self.assertTrue(guard["logs"])
            self.assertIn("entire drive", guard["drive"])

    def test_runtime_config_is_written_under_isolated_keivotos_home(self) -> None:
        with isolated_home() as temporary:
            environment = {**os.environ, "KEIVOTOS_HOME": str(temporary)}
            code = (
                "import sys; "
                f"sys.path.insert(0, {str(ROOT / 'backend')!r}); "
                "import config; "
                "config.save_config({'thumbnail_cache_limit_gb': 5}); "
                "print(config.get_config_path())"
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            runtime_config = Path(result.stdout.strip())
            self.assertEqual(runtime_config, temporary / "config.json")
            self.assertEqual(json.loads(runtime_config.read_text(encoding="utf-8"))["thumbnail_cache_limit_gb"], 5)

    def test_backup_destination_is_fixed_even_with_a_legacy_override(self) -> None:
        with isolated_home() as temporary:
            (temporary / "config.json").write_text(
                json.dumps({"backup_destination": str(temporary / "old-custom-backups")}),
                encoding="utf-8",
            )
            environment = {**os.environ, "KEIVOTOS_HOME": str(temporary)}
            code = (
                "import json, sys; from pathlib import Path; "
                f"sys.path.insert(0, {str(ROOT / 'backend')!r}); "
                "import config; "
                "config.save_config({'thumbnail_cache_limit_gb': 5}); "
                "saved=json.loads(Path(config.get_config_path()).read_text(encoding='utf-8')); "
                "print(json.dumps({"
                "'destination': config.get_backup_config()['destination'], "
                "'snapshot_has_legacy': 'backup_destination' in config.runtime_config_snapshot(), "
                "'saved_has_legacy': 'backup_destination' in saved"
                "}))"
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            status = json.loads(result.stdout)
            self.assertEqual(Path(status["destination"]), temporary / "backups" / "danbooru")
            self.assertFalse(status["snapshot_has_legacy"])
            self.assertFalse(status["saved_has_legacy"])

    def test_product_identity_and_portable_check(self) -> None:
        with isolated_home() as temporary:
            environment = {**os.environ, "KEIVOTOS_HOME": str(temporary)}
            version = subprocess.run(
                [sys.executable, "app.py", "--version"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertEqual(version.stdout.strip(), f"{DISPLAY_NAME} {VERSION}")
            portable = subprocess.run(
                [sys.executable, "app.py", "--portable-check"],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn(f"Writable home: {temporary}", portable.stdout)
            self.assertIn("Frontend: ok", portable.stdout)
            self.assertIn("Backend: ok", portable.stdout)
            self.assertIn("Folder picker: ok", portable.stdout)

    def test_windows_spec_collects_the_backend_composition_root(self) -> None:
        spec = (ROOT / "packaging" / "windows" / "Keivotos.spec").read_text(encoding="utf-8")
        self.assertIn(
            'hiddenimports=["server", "runtime_logging", *UVICORN_HIDDEN_IMPORTS]',
            spec,
        )
        for package in (
            "uvicorn.lifespan",
            "uvicorn.loops",
            "uvicorn.protocols.http",
            "uvicorn.protocols.websockets",
        ):
            self.assertIn(f'collect_submodules("{package}")', spec)

    def test_windows_release_cleanup_and_portable_smoke_are_guarded(self) -> None:
        script = (ROOT / "scripts" / "release" / "build_windows.ps1").read_text(encoding="utf-8")
        version_script = (ROOT / "scripts" / "release" / "set_version.py").read_text(encoding="utf-8")
        self.assertIn("$RepositoryPrefix", script)
        self.assertIn("$CleanupPaths", script)
        self.assertLess(script.index("foreach ($Path in $CleanupPaths)"), script.index("Remove-Item -LiteralPath $Path -Recurse -Force"))
        self.assertNotIn("$ResolvedParent.StartsWith($Root", script)
        self.assertIn('Get-Content -LiteralPath (Join-Path $Root "backend\\product.py") -Raw', script)
        self.assertIn("does not match product.py version", script)
        self.assertIn("Get-Command uv -ErrorAction SilentlyContinue", script)
        self.assertIn('$UserProfileDirectory ".local\\bin\\uv.exe"', script)
        self.assertIn("& $UvPath sync --locked --python 3.11 --group build", script)
        self.assertIn('[str(uv), "lock", "--project", str(ROOT)]', version_script)
        self.assertIn('"uv.lock, package.json, package-lock.json', version_script)
        self.assertIn("Start-Process -FilePath $Executable", script)
        self.assertIn("-WindowStyle Hidden -PassThru", script)
        self.assertIn("Invoke-WebRequest", script)
        self.assertIn("$env:KEIVOTOS_HOME = $SmokeHome", script)

    def test_web_document_uses_suite_identity(self) -> None:
        index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>Keivotos - Danbooru</title>", index)
        self.assertIn('href="/favicon.png"', index)
        self.assertTrue((ROOT / "frontend" / "public" / "keivotos-logo.png").is_file())
        self.assertTrue((ROOT / "packaging" / "windows" / "assets" / "keivotos.ico").is_file())

    def test_original_media_has_no_delete_controls(self) -> None:
        detail = (ROOT / "frontend" / "src" / "components" / "ImageDetail.svelte").read_text(encoding="utf-8")
        grid = (ROOT / "frontend" / "src" / "components" / "ImageGrid.svelte").read_text(encoding="utf-8")
        api_client = (ROOT / "frontend" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
        self.assertNotIn("Delete Image", detail)
        self.assertNotIn("deleteImage", api_client)
        self.assertNotIn("deleteSelectedImages", grid)
        self.assertNotIn("deleteImages", api_client)

    def test_launcher_and_brand_assets_use_the_keivotos_defaults(self) -> None:
        sys.path.insert(0, str(ROOT / "backend"))
        try:
            from product import DEFAULT_HOST, DEFAULT_ORIGIN, DEFAULT_PORT, DISPLAY_NAME, MODULE_NAME, SUITE_NAME, WEB_TITLE
        finally:
            sys.path.pop(0)
        self.assertEqual((DEFAULT_HOST, DEFAULT_PORT), ("localhost", 52325))
        self.assertEqual(DEFAULT_ORIGIN, "http://localhost:52325")
        self.assertEqual(DISPLAY_NAME, "Keivotos - Danbooru")
        self.assertEqual(WEB_TITLE, DISPLAY_NAME)

        canonical = (
            ROOT / "assets" / "branding" / "keivotos" / "source" / "keivotos-angular-logo.svg"
        ).read_text(encoding="utf-8")
        module_mark = (
            ROOT / "assets" / "branding" / "danbooru" / "icon.svg"
        ).read_text(encoding="utf-8")
        module_profile_mark = (
            ROOT / "assets" / "branding" / "danbooru" / "profile-avatar.svg"
        ).read_text(encoding="utf-8")
        self.assertIn("Keivotos angular avatar logo", canonical)
        self.assertIn('aria-label="Danbooru"', module_mark)
        self.assertEqual((ROOT / "frontend" / "public" / "logo.svg").read_text(encoding="utf-8"), module_mark)
        self.assertEqual((ROOT / "frontend" / "public" / "favicon.svg").read_text(encoding="utf-8"), canonical)
        self.assertEqual(
            (ROOT / "frontend" / "public" / "profile-avatar.svg").read_text(encoding="utf-8"),
            module_profile_mark,
        )
        user_menu = (ROOT / "frontend" / "src" / "components" / "UserMenu.svelte").read_text(encoding="utf-8")
        profile_view = (ROOT / "frontend" / "src" / "components" / "ProfileView.svelte").read_text(encoding="utf-8")
        stores = (ROOT / "frontend" / "src" / "lib" / "stores.ts").read_text(encoding="utf-8")
        frontend_product = (ROOT / "frontend" / "src" / "lib" / "product.ts").read_text(encoding="utf-8")
        app_drawer = (ROOT / "frontend" / "src" / "components" / "AppDrawer.svelte").read_text(encoding="utf-8")
        self.assertIn('src="/profile-avatar.svg"', user_menu)
        self.assertNotIn('src="/keivotos-logo.png"', user_menu)
        self.assertIn(": '/profile-avatar.svg';", profile_view)
        self.assertIn('<img src="/profile-avatar.svg" alt="" class="h-9 w-9', app_drawer)
        self.assertIn("{$profileName}", profile_view)
        self.assertIn('aria-label="Edit profile name"', profile_view)
        self.assertIn('maxlength="40"', profile_view)
        self.assertIn("profileName.load()", profile_view)
        self.assertIn(f"export const SUITE_NAME = {SUITE_NAME!r};", frontend_product)
        self.assertIn(f"export const MODULE_NAME = {MODULE_NAME!r};", frontend_product)
        self.assertIn("export const MODULE_DISPLAY_NAME = MODULE_NAME.replace('-', ' ');", frontend_product)
        self.assertIn("export const DEFAULT_PROFILE_NAME = SUITE_NAME;", frontend_product)
        self.assertIn("export const STORAGE_PREFIX = 'danbooru:';", frontend_product)
        self.assertIn("migratePersistedStorage();", frontend_product)
        for component_name in (
            "AppDrawer.svelte",
            "AppSettingsModal.svelte",
            "BackupRestoreSettings.svelte",
            "TopBar.svelte",
        ):
            component = (
                ROOT / "frontend" / "src" / "components" / component_name
            ).read_text(encoding="utf-8")
            self.assertNotIn(SUITE_NAME, component)
            self.assertNotIn(f"'{MODULE_NAME}'", component)
            self.assertNotIn(f'"{MODULE_NAME}"', component)
        self.assertNotIn("STORAGE_PREFIX", stores)
        self.assertIn("api.getUserSetting('profile_name')", stores)
        self.assertIn("api.putUserSetting('profile_name'", stores)

        launcher = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('CONSOLE_ICON_PATH = ROOT / "assets" / "branding" / "keivotos" / "keivotos.ico"', launcher)
        self.assertIn("SetConsoleTitleW(WEB_TITLE)", launcher)
        self.assertIn("wm_seticon = 0x0080", launcher)
        self.assertIn("user32.SendMessageW(console_window, wm_seticon, icon_kind, icon)", launcher)


if __name__ == "__main__":
    unittest.main()
