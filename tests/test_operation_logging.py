from __future__ import annotations

import base64
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from modules.danbooru import pipeline, tools
from runtime_logging import redact_log_text


class OperationLoggingTests(unittest.TestCase):
    def test_console_and_runtime_show_work_but_access_retains_polling(self):
        with tempfile.TemporaryDirectory() as directory:
            code = """
import json, logging, sys
sys.path.insert(0, sys.argv[1])
from runtime_logging import configure_runtime_logging
runtime, access = configure_runtime_logging()
logging.getLogger('keivotos').info('import: sample.jpg matched post 123')
logger = logging.getLogger('uvicorn.access')
for method, status in [('GET', 200), ('POST', 201), ('GET', 500)]:
    logger.info('%s - "%s %s HTTP/%s" %d', '127.0.0.1:1', method, '/api/sample', '1.1', status)
logging.shutdown()
print(json.dumps([str(runtime), str(access)]))
"""
            result = subprocess.run(
                [sys.executable, "-c", code, str(ROOT / "backend")],
                env={**os.environ, "KEIVOTOS_HOME": directory},
                capture_output=True, text=True, check=True,
            )
            runtime, access = [Path(path).read_text() for path in json.loads(result.stdout)]
        self.assertIn("sample.jpg matched post 123", result.stderr)
        self.assertIn("sample.jpg matched post 123", runtime)
        self.assertNotIn('GET /api/sample HTTP/1.1" 200', result.stderr)
        self.assertNotIn('GET /api/sample HTTP/1.1" 200', runtime)
        self.assertIn('GET /api/sample HTTP/1.1" 200', access)
        self.assertIn('GET /api/sample HTTP/1.1" 500', result.stderr)
        self.assertIn('POST /api/sample HTTP/1.1" 201', result.stderr)

    def test_subprocess_results_errors_and_summary_reach_logger_without_secrets(self):
        secret = "private-key+42"
        token = base64.b64encode(f"tester:{secret}".encode()).decode()
        event = {"filename": "sample.png", "status": "error", "index": 1, "total": 1,
                 "detail": f"connection reset https://example.test/posts?api_key={secret}"}
        code = (
            "import sys\n"
            "print('STAGE:metadata')\n"
            f"print('Authorization: Basic {token}')\n"
            f"print('FILE_STATUS:' + {json.dumps(event)!r})\n"
            "print('PROGRESS:1/1')\n"
            "sys.exit(1)\n"
        )
        tool_id = "logging-test"
        try:
            with self.assertLogs("keivotos.danbooru.jobs", level="INFO") as captured:
                result = tools._launch_tool(tool_id, [[sys.executable, "-c", code]],
                    environment={**os.environ, "DANBOORU_USERNAME": "tester", "DANBOORU_API_KEY": secret})
                self.assertEqual(result["status"], "started")
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if tools.active_tool_id() != tool_id:
                        break
                    time.sleep(0.01)
                self.assertNotEqual(tools.active_tool_id(), tool_id, "worker did not finish")
            task = tools.tool_task_snapshot(tool_id)
        finally:
            tools._running_tasks.pop(tool_id, None)
        output = "\n".join(captured.output)
        self.assertIn("stage metadata", output)
        self.assertIn("sample.png | error | connection reset", output)
        self.assertIn("failed (exit 1)", output)
        self.assertNotIn("FILE_STATUS:", output)
        self.assertNotIn("PROGRESS:", output)
        self.assertNotIn(secret, output + json.dumps(task))
        self.assertNotIn(token, output + json.dumps(task))
        self.assertEqual(task["status"], "error")
        self.assertEqual(task["result_counts"]["error"], 1)
        self.assertIn("connection reset", task["file_results"][0]["detail"])

    def test_worker_start_failure_is_logged_and_releases_reservation(self):
        class ImmediateThread:
            def __init__(self, target, **kwargs):
                self.target = target

            def start(self):
                self.target()

        try:
            with patch.object(tools.threading, "Thread", ImmediateThread), \
                 patch.object(tools.subprocess, "Popen", side_effect=OSError("cannot start helper")), \
                 self.assertLogs("keivotos.danbooru.jobs", level="ERROR") as captured:
                tools._launch_tool("failed-start-test", [["unused"]], environment=dict(os.environ))
            self.assertIn("Traceback", "\n".join(captured.output))
            self.assertIn("cannot start helper", "\n".join(captured.output))
            self.assertIsNone(tools.active_tool_id())
            self.assertEqual(tools.tool_task_snapshot("failed-start-test")["status"], "error")
        finally:
            tools._running_tasks.pop("failed-start-test", None)

    def test_network_retry_logging_keeps_existing_retry_count_and_delay(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'[{"id": 123}]'
        output = io.StringIO()
        with patch.object(pipeline.urllib.request, "urlopen", side_effect=[
            urllib.error.URLError(ConnectionResetError(10054, "connection reset")), response,
        ]) as request, patch.object(pipeline.time, "sleep") as sleep, redirect_stdout(output):
            result = pipeline.request_json("/posts.json", {"tags": "private-search"}, "user", "key", 2)
        self.assertEqual(result, [{"id": 123}])
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(2)
        self.assertIn("attempt 1/3", output.getvalue())
        self.assertIn("10054", output.getvalue())
        self.assertIn("retry in 2s", output.getvalue())
        self.assertIn("attempt 2/3) succeeded", output.getvalue())
        self.assertNotIn("private-search", output.getvalue())

    def test_exhausted_network_error_logs_endpoint_without_key(self):
        output = io.StringIO()
        error = urllib.error.URLError("failed https://example.test/?api_key=secret-value")
        with patch.object(pipeline.urllib.request, "urlopen", side_effect=error), redirect_stdout(output):
            with self.assertRaises(urllib.error.URLError):
                pipeline.request_json("/posts/123.json", {}, "user", "secret-value", 0)
        self.assertIn("GET /posts/123.json", output.getvalue())
        self.assertIn("retries exhausted", output.getvalue())
        self.assertNotIn("secret-value", output.getvalue())

    def test_rate_limit_and_authentication_remain_distinct(self):
        for status in (429, 401, 403, 500):
            with self.subTest(status=status):
                error = urllib.error.HTTPError("https://example.test/", status, "failure", {}, None)
                output = io.StringIO()
                with patch.object(pipeline.urllib.request, "urlopen", side_effect=error) as request, \
                     patch.object(pipeline.time, "sleep") as sleep, redirect_stdout(output):
                    with self.assertRaises(urllib.error.HTTPError):
                        pipeline.request_json("/posts.json", {}, None, None, 1)
                self.assertIn(f"HTTP {status}", output.getvalue())
                self.assertEqual(request.call_count, 2 if status == 429 else 1)
                if status == 429:
                    sleep.assert_called_once_with(60)
                else:
                    sleep.assert_not_called()

    def test_redaction_preserves_useful_error_details(self):
        result = redact_log_text(
            "10054 https://user:pass@example.test/posts?tags=private "
            "Authorization: Bearer token-value api_key=another-value private%2Bkey",
            ("private+key",),
        )
        self.assertIn("10054", result)
        self.assertIn("example.test/posts", result)
        for secret in ("user:pass", "tags=private", "token-value", "another-value", "private%2Bkey"):
            self.assertNotIn(secret, result)


if __name__ == "__main__":
    unittest.main()
