"""Protect shared maintenance HTTP behavior before separating the tools router."""
from contextlib import contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi import HTTPException
from models import BackupCreateRequest, BackupRestoreRequest, ThumbnailCacheLimitUpdate
from routers import backups
from routers import recovery
from routers import cache


class SuiteMaintenanceRouteTests(unittest.TestCase):
    def test_busy_danbooru_job_blocks_suite_backup_with_original_guard(self):
        from modules.danbooru import tools

        self.assertIs(backups.exclusive_tool_operation, tools.exclusive_tool_operation)
        import maintenance
        with patch.object(maintenance, "_active_tool_id", "sync"), patch.object(backups, "create_backup_bundle") as create:
            with self.assertRaises(HTTPException) as caught:
                backups.create_metadata_backup(BackupCreateRequest())
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(caught.exception.detail, "Wait for sync to finish before backing up")
            create.assert_not_called()

    def test_shared_endpoints_are_absent_from_danbooru_descriptor(self):
        from modules.danbooru import descriptor
        from routers import storage

        shared = {(route.path, method) for owner in (backups, recovery, storage, cache)
                  for route in owner.router.routes for method in route.methods}
        self.assertEqual(len(shared), 16)
        module = {(route.path, method) for router in descriptor(Path("unused"), "test").routers()
                  for route in router.routes for method in route.methods}
        self.assertFalse(shared & module)

    def test_backup_and_restore_keep_exclusive_window(self):
        for name, request, helper, label in (
            ("create_metadata_backup", BackupCreateRequest(components={"user_database": True}), "create_backup_bundle", "backing up"),
            ("restore_metadata_backup", BackupRestoreRequest(name="fixture.zip"), "restore_backup_bundle", "restoring"),
        ):
            events = []

            @contextmanager
            def guard(operation):
                self.assertEqual(operation, label)
                events.append("enter")
                yield
                events.append("exit")

            def work(value):
                self.assertEqual(events, ["enter"])
                self.assertEqual(value, request.components if hasattr(request, "components") else request.name)
                events.append("work")
                return {"status": "fixture"}

            with patch.object(backups, "exclusive_tool_operation", guard), patch.object(backups, helper, work):
                self.assertEqual(getattr(backups, name)(request), {"status": "fixture"})
            self.assertEqual(events, ["enter", "work", "exit"])
            with patch.object(backups, "exclusive_tool_operation", side_effect=RuntimeError("busy")), patch.object(backups, helper) as blocked:
                with self.assertRaises(HTTPException) as caught:
                    getattr(backups, name)(request)
                self.assertEqual((caught.exception.status_code, caught.exception.detail), (409, "busy"))
                blocked.assert_not_called()

    def test_backup_errors_and_inspection_basename(self):
        @contextmanager
        def guard(_name):
            yield

        for name, request, helper in (
            ("create_metadata_backup", BackupCreateRequest(), "create_backup_bundle"),
            ("restore_metadata_backup", BackupRestoreRequest(name="fixture.zip"), "restore_backup_bundle"),
        ):
            for error, status in ((ValueError("invalid"), 400), (FileNotFoundError("missing"), 400), (RuntimeError("busy"), 409)):
                with self.subTest(name=name, error=type(error).__name__), patch.object(backups, "exclusive_tool_operation", guard), patch.object(backups, helper, side_effect=error):
                    with self.assertRaises(HTTPException) as caught:
                        getattr(backups, name)(request)
                    self.assertEqual(caught.exception.status_code, status)
        with patch.object(backups, "get_backup_config", return_value={"destination": "/fixture/backups"}), patch.object(
            backups, "inspect_backup_bundle", return_value={"valid": True},
        ) as inspect:
            self.assertEqual(backups.inspect_metadata_backup("../fixture.zip"), {"valid": True})
            inspect.assert_called_once_with(Path("/fixture/backups/fixture.zip"))

    def test_checkpoint_preserves_conflict_response(self):
        with patch.object(recovery, "create_local_recovery_checkpoint", return_value={"created": True}) as create:
            self.assertEqual(recovery.create_recovery_checkpoint(), {"created": True})
            create.assert_called_once_with("manual")
        with patch.object(recovery, "create_local_recovery_checkpoint", side_effect=OSError("fixture failure")):
            with self.assertRaises(HTTPException) as caught:
                recovery.create_recovery_checkpoint()
            self.assertEqual((caught.exception.status_code, caught.exception.detail), (409, "fixture failure"))

    def test_cache_cleanup_clear_and_limit_forwarding(self):
        with patch.object(cache, "_valid_thumbnail_keys", return_value={"valid"}), patch.object(cache, "cleanup_thumbnail_cache", return_value={"removed": 2}) as cleanup:
            self.assertEqual(cache.cleanup_thumbnails(), {"removed": 2})
            cleanup.assert_called_once_with({"valid"})
        with patch.object(cache, "clear_thumbnail_cache", return_value=3), patch.object(cache, "thumbnail_cache_status", return_value={"size_bytes": 0}):
            self.assertEqual(cache.clear_thumbnails(), {"size_bytes": 0, "removed": 3})
        with patch.object(cache, "save_config") as save, patch.object(cache, "prune_thumbnail_cache", return_value={"removed": 1}) as prune:
            self.assertEqual(cache.update_thumbnail_limit(ThumbnailCacheLimitUpdate(limit_gb=2)), {"removed": 1})
            save.assert_called_once_with({"thumbnail_cache_limit_gb": 2})
            prune.assert_called_once_with(2 * 1024 ** 3)
