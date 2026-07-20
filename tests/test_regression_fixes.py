from __future__ import annotations

import io
import json
import os
import runpy
import shutil
import socket
import sqlite3
import subprocess
import sys
import unittest
import uuid
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
import uvicorn


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import app as launcher  # noqa: E402
import core  # noqa: E402
from models import CollectionCreate, CollectionItemsUpdate  # noqa: E402
from routers import collections  # noqa: E402


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return dict(zip((column[0] for column in cursor.description), row))


class RegressionFixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = ROOT / "tests" / f".tmp-regressions-{uuid.uuid4().hex}"
        self.temp.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_relation_refresh_preserves_the_parents_own_parent(self) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = _row_factory
        connection.execute(
            "CREATE TABLE posts(danbooru_post_id INTEGER PRIMARY KEY, parent_id INTEGER, has_children INTEGER, child_ids_json TEXT)"
        )
        connection.executemany(
            "INSERT INTO posts(danbooru_post_id, parent_id) VALUES (?, ?)",
            [(50, None), (100, 50), (200, 100)],
        )
        with (
            patch.object(
                core,
                "danbooru_json",
                return_value={"id": 200, "parent_id": 100, "has_children": False, "children": []},
            ),
            patch.object(
                core,
                "danbooru_child_search",
                return_value=[{"id": 200, "parent_id": 100, "has_children": False, "children": []}],
            ),
        ):
            core.refresh_relation_cache(connection, 200)

        parent = connection.execute(
            "SELECT parent_id, has_children, child_ids_json FROM posts WHERE danbooru_post_id=100"
        ).fetchone()
        connection.close()
        self.assertEqual(parent["parent_id"], 50)
        self.assertEqual(parent["has_children"], 1)
        self.assertEqual(json.loads(parent["child_ids_json"]), [200])

    def test_collection_create_rejects_blank_names(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            collections.create_collection(CollectionCreate(name="   ", description="ignored"))
        self.assertEqual(caught.exception.status_code, 400)

    def test_collection_membership_update_returns_404_for_missing_collection(self) -> None:
        user_db = self.temp / "user.sqlite"
        connection = sqlite3.connect(user_db)
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE collections(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE collection_items(
                collection_id INTEGER NOT NULL REFERENCES collections(id),
                file_id INTEGER NOT NULL,
                file_path TEXT,
                local_md5 TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(collection_id, file_id)
            );
            """
        )
        connection.close()

        @contextmanager
        def user_connection():
            current = sqlite3.connect(user_db)
            current.row_factory = _row_factory
            current.execute("PRAGMA foreign_keys=ON")
            try:
                yield current
            finally:
                current.close()

        with patch.object(collections, "get_user_db", user_connection):
            with self.assertRaises(HTTPException) as caught:
                collections.update_collection_images(
                    999,
                    CollectionItemsUpdate(action="add", file_ids=[1]),
                )
        self.assertEqual(caught.exception.status_code, 404)

    def test_string_system_exit_from_packaged_helper_returns_one(self) -> None:
        scripts = self.temp / "scripts"
        scripts.mkdir()
        (scripts / "helper.py").write_text("raise SystemExit('helper failed')\n", encoding="utf-8")
        stderr = io.StringIO()
        with patch.object(launcher, "ROOT", self.temp), redirect_stderr(stderr):
            result = launcher._run_helper("helper.py", [])
        self.assertEqual(result, 1)
        self.assertIn("helper failed", stderr.getvalue())

    def test_port_probe_reports_an_existing_listener(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            available, error = launcher._port_available("localhost", port)
        self.assertFalse(available)
        self.assertTrue(error)

    def test_lan_address_filter_accepts_only_private_ipv4(self) -> None:
        allowed = ("10.1.2.3", "100.64.0.1", "169.254.1.2", "172.16.4.5", "192.168.1.25")
        for address in allowed:
            with self.subTest(address=address):
                self.assertTrue(launcher._is_lan_ipv4(address))
        for address in ("127.0.0.1", "8.8.8.8", "::1", "not-an-address"):
            with self.subTest(address=address):
                self.assertFalse(launcher._is_lan_ipv4(address))

    def test_portable_launcher_does_not_accept_lan_flag(self) -> None:
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {launcher.LAN_DEVELOPER_ENV: "1"}),
            patch.object(launcher.sys, "frozen", True, create=True),
            redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as caught:
                launcher.main(["--lan"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("unrecognized arguments: --lan", stderr.getvalue())

    def test_source_launcher_requires_the_local_developer_lan_marker(self) -> None:
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {launcher.LAN_DEVELOPER_ENV: ""}),
            patch.object(launcher.sys, "frozen", False, create=True),
            redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as caught:
                launcher.main(["--lan"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("unrecognized arguments: --lan", stderr.getvalue())

    def test_developer_lan_binds_only_the_discovered_adapter(self) -> None:
        configuration = SimpleNamespace(
            SUITE_HOME=self.temp,
            SUITE_HOME_MIGRATION={"migrated": False},
        )
        runtime_logging = SimpleNamespace(
            configure_runtime_logging=lambda: (self.temp / "runtime.log", self.temp / "access.log")
        )
        with (
            patch.dict(os.environ, {launcher.LAN_DEVELOPER_ENV: "1"}),
            patch.object(launcher.sys, "frozen", False, create=True),
            patch.object(launcher, "_load_configuration", return_value=configuration),
            patch.object(launcher, "_discover_lan_ipv4", return_value="192.168.1.25"),
            patch.object(launcher, "_port_available", return_value=(True, None)),
            patch.object(launcher, "_load_asgi_app", return_value=object()),
            patch.object(launcher.importlib, "import_module", return_value=runtime_logging),
            patch.object(uvicorn, "run") as run_server,
        ):
            result = launcher.main(["--lan", "--no-browser", "--port", "52400"])
        self.assertEqual(result, 0)
        self.assertEqual(run_server.call_args.kwargs["host"], "192.168.1.25")
        self.assertNotEqual(run_server.call_args.kwargs["host"], "0.0.0.0")

    def test_malformed_runtime_config_fails_cleanly_and_is_logged(self) -> None:
        (self.temp / "config.json").write_text('{"automation_enabled": false,}\n', encoding="utf-8")
        environment = {**os.environ, "KEIVOTOS_HOME": str(self.temp)}
        result = subprocess.run(
            [sys.executable, "app.py", "--version"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
        )
        log_files = list((self.temp / "logs").glob("danbooru-runtime-*.log"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Invalid JSON", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(len(log_files), 1)
        self.assertIn(str(self.temp / "config.json"), log_files[0].read_text(encoding="utf-8"))

    def test_runtime_and_access_logs_are_dated_and_separated(self) -> None:
        environment = {**os.environ, "KEIVOTOS_HOME": str(self.temp)}
        code = (
            "import json, logging, sys; "
            f"sys.path.insert(0, {str(ROOT / 'backend')!r}); "
            "import config; "
            "from runtime_logging import configure_runtime_logging; "
            "runtime_path, access_path = configure_runtime_logging(); "
            "logging.getLogger('keivotos').info('runtime event'); "
            "access = logging.getLogger('uvicorn.access'); "
            "access.info('%s - \"%s %s HTTP/%s\" %d', '127.0.0.1:1', 'GET', '/api/read', '1.1', 200); "
            "access.info('%s - \"%s %s HTTP/%s\" %d', '127.0.0.1:1', 'POST', '/api/change', '1.1', 201); "
            "logging.shutdown(); "
            "storage = config.public_storage_config(); "
            "print(json.dumps([str(runtime_path), str(access_path), storage]))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        runtime_name, access_name, storage = json.loads(result.stdout)
        self.assertRegex(Path(runtime_name).name, r"^danbooru-runtime-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-p\d+\.log$")
        self.assertRegex(Path(access_name).name, r"^danbooru-access-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-p\d+\.log$")
        self.assertEqual(storage["runtime_log_file"], runtime_name)
        self.assertEqual(storage["access_log_file"], access_name)
        self.assertEqual(storage["log_retention_files"], 30)
        runtime_text = Path(runtime_name).read_text(encoding="utf-8")
        access_text = Path(access_name).read_text(encoding="utf-8")
        self.assertIn("runtime event", runtime_text)
        self.assertIn("POST /api/change", runtime_text)
        self.assertNotIn("GET /api/read", runtime_text)
        self.assertIn("GET /api/read", access_text)
        self.assertIn("POST /api/change", access_text)

    def test_invalid_numeric_config_values_use_safe_defaults(self) -> None:
        (self.temp / "config.json").write_text(
            json.dumps(
                {
                    "automation_interval_minutes": "15 min",
                    "thumbnail_cache_limit_gb": "a lot",
                }
            ),
            encoding="utf-8",
        )
        environment = {**os.environ, "KEIVOTOS_HOME": str(self.temp)}
        code = (
            "import json, sys; "
            f"sys.path.insert(0, {str(ROOT / 'backend')!r}); "
            "import config; "
            "print(json.dumps([config.get_automation_config()['interval_minutes'], "
            "config.get_thumbnail_cache_limit_bytes()]))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout), [15, 10 * 1024 * 1024 * 1024])


if __name__ == "__main__":
    unittest.main()
