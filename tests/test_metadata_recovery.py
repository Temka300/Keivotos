"""Offline recovery, preservation and orchestration regressions."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from contextlib import closing, redirect_stdout, redirect_stderr
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from modules.danbooru import pipeline, network, tools
from modules.danbooru.models import ImportRunRequest
from modules.danbooru.routers import tools as routes
from storage_layout import LibraryRoot

POST = {"id": 123, "rating": "g", "tag_string": "sample_tag", "tag_string_general": "sample_tag"}


class MetadataRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.media = self.root / "media"
        self.media.mkdir()
        self.sidecars = self.root / "module/sidecars"
        self.database = self.root / "index.sqlite"
        self.roots = patch.object(pipeline, "_LIBRARY_ROOTS", [LibraryRoot("test-root", "media", self.media)])
        self.roots.start()
        self.addCleanup(self.roots.stop)
        self.addCleanup(self.temp.cleanup)
        self.output = io.StringIO()

    def file(self, name="sample.png"):
        path = self.media / name
        Image.new("RGB", (4, 4), "red").save(path)
        return path

    def args(self, command="backfill", extra=()):
        options = ["--root", str(self.root), "--sidecar-dir", str(self.sidecars),
                   "--user-db", str(self.root / "user.sqlite"), command]
        if command == "backfill":
            options += ["--use-indexed-md5", "--database", str(self.database), "--delay", "0", "--report-incomplete"]
        else:
            options += ["--output", str(self.database)]
        return pipeline.build_parser().parse_args([*options, *extra, str(self.media)])

    def prepare(self):
        with redirect_stdout(self.output):
            pipeline.run_import_discover(self.args("import-discover"))
            pipeline.run_import_enrich(self.args("import-enrich"))

    def run_backfill(self, extra=()):
        with redirect_stdout(self.output), redirect_stderr(self.output):
            return pipeline.run_backfill(self.args(extra=extra))

    def sidecar(self, path):
        return pipeline.metadata_path_for(path, ".danbooru.json", self.root, self.sidecars)

    def test_partial_tags_survive_finalize_and_retry_only_extra_details(self):
        media = self.file()
        self.prepare()
        with patch.object(pipeline, "find_post_by_md5", return_value=(POST, "indexed_md5", "abc")), \
             patch.object(pipeline, "add_extra_metadata", side_effect=TimeoutError("timed out")):
            self.assertEqual(self.run_backfill(["--extra-metadata"]), 3)
        before = self.sidecar(media).read_bytes()
        saved = json.loads(before)
        self.assertEqual(saved["tags"]["all"], ["sample_tag"])
        self.assertTrue(saved["metadata_pending"]["includes"])
        with redirect_stdout(self.output):
            self.assertEqual(pipeline.run_import_finalize(self.args("import-finalize")), 0)
            self.assertEqual(pipeline.run_import_finalize(self.args("import-finalize", ["--report-incomplete"])), 3)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT status FROM ingest_state").fetchone()[0], "partial")
            self.assertEqual(connection.execute("SELECT danbooru_post_id FROM posts").fetchone()[0], 123)
        with patch.object(pipeline, "find_post_by_md5", side_effect=AssertionError("must reuse the saved post")), \
             patch.object(pipeline, "add_extra_metadata", return_value={**POST, "artist_commentary": "retained"}) as enrich:
            self.assertEqual(self.run_backfill(["--retry-failed"]), 0)
            self.assertTrue(enrich.call_args.args[1])
        after = json.loads(self.sidecar(media).read_text())
        self.assertNotIn("metadata_pending", after)
        self.assertEqual(after["post"]["artist_commentary"], "retained")
        archives = list((self.sidecars.parent / "sidecar_archive").rglob("*.danbooru.json"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].read_bytes(), before)

    def test_limit_counts_unfinished_files_and_retry_skips_known_misses(self):
        first, second = self.file("a.png"), self.file("b.png")
        self.prepare()
        with patch.object(pipeline, "find_post_by_md5", return_value=(POST, "indexed_md5", "abc")):
            self.assertEqual(self.run_backfill(["--limit", "1"]), 0)
        original = self.sidecar(first).read_bytes()
        with patch.object(pipeline, "find_post_by_md5", return_value=(None, None, None)) as find:
            self.assertEqual(self.run_backfill(["--limit", "1"]), 0)
            self.assertEqual(find.call_args.args[0], second)
        with patch.object(pipeline, "find_post_by_md5", side_effect=AssertionError("no work remains")):
            self.assertEqual(self.run_backfill(["--retry-failed"]), 0)
        self.assertEqual(self.sidecar(first).read_bytes(), original)

    def test_outage_stops_after_three_files_and_later_run_resumes(self):
        for index in range(5):
            self.file(f"{index}.png")
        self.prepare()
        with patch.object(pipeline, "find_post_by_md5", side_effect=urllib.error.URLError("reset")) as find:
            self.assertEqual(self.run_backfill(), 3)
            self.assertEqual(find.call_count, 3)
        with patch.object(pipeline, "find_post_by_md5", return_value=(POST, "indexed_md5", "abc")) as find:
            self.assertEqual(self.run_backfill(["--retry-failed"]), 0)
            self.assertEqual(find.call_count, 5)
        self.assertIn("Stopped network work", self.output.getvalue())

    def test_authentication_stops_immediately_without_marking_untried_files_failed(self):
        self.file("a.png")
        self.file("b.png")
        self.prepare()
        error = urllib.error.HTTPError("https://example.test", 401, "Unauthorized", {}, None)
        with patch.object(pipeline, "find_post_by_md5", side_effect=error) as find:
            self.assertEqual(self.run_backfill(), 3)
            self.assertEqual(find.call_count, 1)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM ingest_state WHERE status='error'").fetchone()[0], 1)

    def test_long_server_retry_after_stops_the_whole_batch(self):
        self.file("a.png")
        self.file("b.png")
        self.prepare()
        error = urllib.error.HTTPError("https://example.test", 503, "Unavailable", {"Retry-After": "3600"}, None)
        with patch.object(pipeline, "find_post_by_md5", side_effect=error) as find:
            self.assertEqual(self.run_backfill(), 3)
            self.assertEqual(find.call_count, 1)

    def test_failed_atomic_replacement_keeps_previous_json_and_archive(self):
        media = self.file()
        self.prepare()
        with patch.object(pipeline, "find_post_by_md5", return_value=(POST, "indexed_md5", "abc")):
            self.assertEqual(self.run_backfill(), 0)
        before = self.sidecar(media).read_bytes()
        replace = Path.replace
        def fail_json(source, target):
            if str(target).endswith(".danbooru.json"):
                raise OSError("disk full")
            return replace(source, target)
        with patch.object(pipeline, "find_post_by_md5", return_value=({**POST, "id": 456}, "indexed_md5", "abc")), \
             patch.object(Path, "replace", fail_json):
            self.assertEqual(self.run_backfill(["--overwrite"]), 3)
        self.assertEqual(self.sidecar(media).read_bytes(), before)
        self.assertEqual(next((self.sidecars.parent / "sidecar_archive").rglob("*.danbooru.json")).read_bytes(), before)
        self.assertEqual(list(self.sidecars.rglob("*.tmp")), [])


class NetworkAndJobTests(unittest.TestCase):
    def test_retry_after_bounds_and_error_classification(self):
        for status in (429, 503):
            with self.subTest(status=status):
                error = urllib.error.HTTPError("https://example.test", status, "busy", {"Retry-After": "120"}, None)
                self.assertEqual(network.retry_delay(error, 0), 120)
                error.headers["Retry-After"] = "3600"
                self.assertIsNone(network.retry_delay(error, 0))
        self.assertEqual(network.retry_delay(TimeoutError(), 0), 2)
        self.assertEqual(network.retry_delay(ConnectionResetError(), 2), 8)
        self.assertIsNone(network.retry_delay(ValueError(), 0))
        self.assertIsNone(network.retry_delay(urllib.error.HTTPError("x", 403, "no", {}, None), 0))

    def test_update_is_local_unless_network_explicitly_enabled(self):
        with patch.object(routes, "_sync_scan_paths", return_value=["fixture"]), \
             patch.object(routes, "credential_environment", return_value={}), \
             patch.object(routes, "_launch_tool", return_value={"status": "started"}) as launch:
            routes.run_import(ImportRunRequest(phase="update"))
            self.assertEqual(len(launch.call_args.args[1]), 3)
            self.assertFalse(any("backfill" in command for command in launch.call_args.args[1]))
            with self.assertRaises(Exception) as error:
                routes.run_import(ImportRunRequest(phase="update", fetch_metadata=True))
            self.assertEqual(error.exception.status_code, 400)
            routes.run_import(ImportRunRequest(phase="retry", confirm_network=True))
            self.assertEqual(len(launch.call_args.args[1]), 4)
            self.assertIn("--retry-failed", launch.call_args.args[1][2])
            self.assertEqual(launch.call_args.kwargs["incomplete_steps"], {3, 4})

    def test_incomplete_metadata_finalizes_but_fatal_errors_do_not(self):
        class ImmediateThread:
            def __init__(self, target, **kwargs): self.target = target
            def start(self): self.target()
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "finalized"
            for code in (3, 1):
                with self.subTest(code=code), patch.object(tools.threading, "Thread", ImmediateThread):
                    tool_id = f"incomplete-test-{code}"
                    try:
                        commands = [[sys.executable, "-c", f"raise SystemExit({code})"],
                                    [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"]]
                        tools._launch_tool(tool_id, commands, environment=dict(os.environ), incomplete_steps={1})
                        self.assertEqual(marker.exists(), code == 3)
                        self.assertEqual(tools.tool_task_snapshot(tool_id)["status"], "partial" if code == 3 else "error")
                    finally:
                        tools._running_tasks.pop(tool_id, None)
                        marker.unlink(missing_ok=True)
        self.assertIsNone(tools.active_tool_id())


if __name__ == "__main__":
    unittest.main()
