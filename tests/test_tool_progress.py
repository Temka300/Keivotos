from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import core  # noqa: E402
from routers import tools as tool_routes  # noqa: E402


class ToolProgressTests(unittest.TestCase):
    def test_task_snapshots_do_not_share_mutable_worker_state(self) -> None:
        core._running_tasks["snapshot-test"] = {
            "status": "running",
            "file_results": [{"filename": "one.jpg"}],
        }
        try:
            snapshot = core.tool_task_snapshot("snapshot-test")
            snapshot["file_results"].append({"filename": "mutated.jpg"})
            current = core.tool_task_snapshot("snapshot-test")
        finally:
            core._running_tasks.pop("snapshot-test", None)

        self.assertEqual(current["file_results"], [{"filename": "one.jpg"}])

    def test_import_task_can_return_only_results_after_last_seen_index(self) -> None:
        core._running_tasks["import"] = {
            "status": "running",
            "output": "",
            "progress": 3,
            "total": 10,
            "file_results": [
                {"filename": f"{index}.jpg", "path": str(index), "status": "matched", "index": index, "total": 10}
                for index in range(1, 4)
            ],
        }
        try:
            payload = tool_routes.import_pipeline_task(after_index=2)
        finally:
            core._running_tasks.pop("import", None)

        self.assertEqual([result["index"] for result in payload["file_results"]], [3])

    def test_structured_file_status_is_exposed_to_settings(self) -> None:
        event = json.dumps(
            {
                "path": r"D:\Library\sample.png",
                "filename": "sample.png",
                "status": "matched",
                "index": 1,
                "total": 1,
                "detail": "Post 123 via indexed_md5",
            }
        )
        command = [
            sys.executable,
            "-c",
            f"print('STAGE:metadata'); print('FILE_STATUS:' + {event!r}); print('PROGRESS:1/1')",
        ]
        result = core._launch_tool("progress-protocol-test", [command])
        self.assertEqual(result["status"], "started")

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = core._running_tasks["progress-protocol-test"]
            if task["status"] != "running":
                break
            time.sleep(0.02)

        task = core._running_tasks["progress-protocol-test"]
        self.assertEqual(task["status"], "done")
        self.assertEqual(task["current_file"], "sample.png")
        self.assertEqual(task["current_file_status"], "matched")
        self.assertEqual(task["result_counts"]["matched"], 1)
        self.assertEqual(task["file_results"][0]["detail"], "Post 123 via indexed_md5")
        self.assertEqual((task["progress"], task["total"]), (1, 1))

    def test_long_import_keeps_only_bounded_recent_state(self) -> None:
        command = [
            sys.executable,
            "-c",
            (
                "import json\n"
                "for index in range(300):\n"
                " print('FILE_STATUS:' + json.dumps({'path': str(index), 'filename': f'{index}.jpg', "
                "'status': 'matched', 'index': index, 'total': 300}))\n"
                " print(f'console line {index}')\n"
            ),
        ]
        result = core._launch_tool("bounded-progress-test", [command])
        self.assertEqual(result["status"], "started")

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = core._running_tasks["bounded-progress-test"]
            if task["status"] != "running":
                break
            time.sleep(0.02)

        task = core._running_tasks["bounded-progress-test"]
        self.assertEqual(task["status"], "done")
        self.assertEqual(len(task["file_results"]), 250)
        self.assertEqual(task["file_results"][0]["filename"], "50.jpg")
        self.assertNotIn("console line 0\n", task["output"])
        self.assertIn("console line 299\n", task["output"])


if __name__ == "__main__":
    unittest.main()
