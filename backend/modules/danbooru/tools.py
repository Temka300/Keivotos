"""Running the gallery-dl pipeline as a subprocess: commands, state, progress.

Moved verbatim from ``core.py`` apart from one deliberate fix noted at
``SCRIPT_PATH``. Owns the one-tool-at-a-time gate, the in-memory task registry
consumed by Settings polling, the structured STAGE/PROGRESS/FILE_STATUS protocol,
cancellation, and the post-success recovery checkpoint.

The task state below is module-level and mutable by design; ``core`` imports the
same objects back, so existing readers observe the same registry.

No ``core`` import.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from config import (
    CODE_ROOT,
    DATA_DB_PATH,
    DATA_ROOT,
    GALLERY_DL_DIR,
    SCAN_FOLDERS,
    SIDECAR_DIR,
    USER_DB_PATH,
)
from credentials import credential_environment
from local_recovery import create_local_recovery_checkpoint
from modules.danbooru.folder_registry import registered_folder_rows
from modules.danbooru.home import clear_home_caches


# Resolved against the code root rather than this file's location: the old
# `__file__`-relative form silently required living one level below the root.
SCRIPT_PATH = CODE_ROOT / "scripts" / "danbooru_gallery_dl.py"
PROJECT_ROOT = DATA_ROOT
TOOL_WORKING_DIRECTORY = SCRIPT_PATH.parent.parent

_running_tasks: dict[str, dict[str, Any]] = {}
_running_processes: dict[str, subprocess.Popen[str]] = {}
_tool_state_lock = threading.RLock()
_tool_operation_lock = threading.RLock()
_active_tool_id: str | None = None


def active_tool_id() -> str | None:
    """Return the live tool owner while holding the shared state lock."""
    with _tool_state_lock:
        return _active_tool_id


def tool_task_snapshot(tool_id: str) -> dict[str, Any] | None:
    """Return request-safe task state while the worker may still be updating it."""
    with _tool_state_lock:
        task = _running_tasks.get(tool_id)
        return copy.deepcopy(task) if task is not None else None


@contextmanager
def exclusive_tool_operation(operation_name: str):
    """Prevent a restore/backup window from racing a newly launched tool."""
    with _tool_operation_lock:
        with _tool_state_lock:
            if _active_tool_id:
                raise RuntimeError(f"Wait for {_active_tool_id} to finish before {operation_name}")
        yield


def _tool_base_command() -> list[str]:
    launcher = (
        [sys.executable, "--pipeline"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-Bu", str(SCRIPT_PATH)]
    )
    return [
        *launcher,
        "--root", str(PROJECT_ROOT),
        "--gallery-dl-dir", str(GALLERY_DL_DIR),
        "--sidecar-dir", str(SIDECAR_DIR),
        "--user-db", str(USER_DB_PATH),
    ]


def _sync_scan_paths() -> list[str]:
    """Every folder a full sync should cover: scan folders plus registered folders."""
    paths: list[str] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        if not path.is_dir():
            return
        key = os.path.normcase(str(path))
        if key in seen:
            return
        seen.add(key)
        paths.append(str(path))

    for name in SCAN_FOLDERS:
        add(DATA_ROOT / name)
    if not paths:
        add(DATA_ROOT)
    for row in registered_folder_rows():
        if row["path"]:
            add(Path(row["path"]))
        else:
            add(DATA_ROOT / row["name"])
    return paths


def _extra_root_args() -> list[str]:
    """--extra-root flags for registered folders living outside the data root."""
    args: list[str] = []
    resolved_root = DATA_ROOT.resolve(strict=False)
    for row in registered_folder_rows():
        if not row["path"]:
            continue
        resolved = Path(row["path"]).resolve(strict=False)
        try:
            resolved.relative_to(resolved_root)
        except ValueError:
            args.extend(["--extra-root", str(resolved)])
    return args


def _sync_command(paths: list[str]) -> list[str]:
    return [
        *_tool_base_command(),
        "sync", "--output", str(DATA_DB_PATH), "--no-raw-json",
        *paths,
    ]


def _import_discover_command(paths: list[str]) -> list[str]:
    return [
        *_tool_base_command(),
        "import-discover", "--output", str(DATA_DB_PATH),
        *paths,
    ]


def _import_enrich_command(paths: list[str]) -> list[str]:
    return [
        *_tool_base_command(),
        "import-enrich", "--output", str(DATA_DB_PATH), "--workers", "3",
        *paths,
    ]


def _import_finalize_command(paths: list[str]) -> list[str]:
    return [
        *_tool_base_command(),
        "import-finalize", "--output", str(DATA_DB_PATH), "--no-raw-json",
        *paths,
    ]


def _start_sync_run(paths: list[str]) -> dict[str, Any]:
    return _launch_tool("sync", [_sync_command(paths)])


def _start_folder_import(paths: list[str]) -> dict[str, Any]:
    return _start_sync_run(paths)










def _launch_tool(
    tool_id: str,
    tool_commands: list[list[str]],
    *,
    environment: dict[str, str] | None = None,
    stage_names: list[str] | None = None,
    on_success: Callable[[], str | None] | None = None,
) -> dict[str, Any]:
    global _active_tool_id
    with _tool_operation_lock:
        with _tool_state_lock:
            if _active_tool_id:
                status = "already_running" if _active_tool_id == tool_id else "busy"
                return {"status": status, "active_tool_id": _active_tool_id}
            _active_tool_id = tool_id
            _running_tasks[tool_id] = {
                "status": "running",
                "output": "",
                "progress": 0,
                "total": 0,
                "stage": (stage_names or [None])[0],
                "stage_index": 1,
                "stage_total": len(tool_commands),
                "cancellable": True,
                "current_file": None,
                "current_file_path": None,
                "current_file_status": None,
                "file_results": [],
                "result_counts": {"matched": 0, "no_match": 0, "error": 0},
            }

    def _run():
        global _active_tool_id
        try:
            # Keep only the console tail exposed to Settings. A 40k-file import
            # must not retain every subprocess line for the lifetime of the job.
            lines: deque[str] = deque(maxlen=100)
            for step_index, cmd in enumerate(tool_commands, 1):
                with _tool_state_lock:
                    task = _running_tasks[tool_id]
                    if task["status"] == "cancelling":
                        task["status"] = "cancelled"
                        return
                    stage = (
                        stage_names[step_index - 1]
                        if stage_names and step_index <= len(stage_names)
                        else f"Step {step_index} of {len(tool_commands)}"
                    )
                    task["stage_index"] = step_index
                    task["stage"] = stage
                    if len(tool_commands) > 1:
                        lines.append(f"{stage}\n")
                        task.update(
                            {
                                "output": "".join(lines),
                                "progress": 0,
                                "total": 0,
                                "current_file": None,
                                "current_file_path": None,
                                "current_file_status": None,
                            }
                        )
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(TOOL_WORKING_DIRECTORY),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=environment or credential_environment(),
                )
                with _tool_state_lock:
                    _running_processes[tool_id] = proc
                assert proc.stdout is not None
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if line.startswith("STAGE:"):
                        with _tool_state_lock:
                            _running_tasks[tool_id]["stage"] = line.strip().split(":", 1)[1].replace("_", " ").title()
                        continue
                    if line.startswith("PROGRESS:"):
                        parts = line.strip().split(":", 1)[1].split("/")
                        if len(parts) == 2:
                            try:
                                progress = int(parts[0])
                                total = int(parts[1])
                            except ValueError:
                                pass
                            else:
                                with _tool_state_lock:
                                    _running_tasks[tool_id].update({"progress": progress, "total": total})
                        continue
                    if line.startswith("FILE_STATUS:"):
                        try:
                            event = json.loads(line.split(":", 1)[1])
                        except (json.JSONDecodeError, TypeError):
                            continue
                        filename = str(event.get("filename") or Path(str(event.get("path") or "")).name)
                        status = str(event.get("status") or "working")
                        with _tool_state_lock:
                            task = _running_tasks[tool_id]
                            task["current_file"] = filename or None
                            task["current_file_path"] = str(event.get("path") or "") or None
                            task["current_file_status"] = status
                            if status in {"matched", "no_match", "error"}:
                                result = {
                                    "filename": filename,
                                    "path": str(event.get("path") or ""),
                                    "status": status,
                                    "detail": str(event.get("detail") or ""),
                                    "index": event.get("index"),
                                    "total": event.get("total"),
                                }
                                results = task.setdefault("file_results", [])
                                results.append(result)
                                if len(results) > 250:
                                    del results[:-250]
                                counts = task.setdefault("result_counts", {})
                                counts[status] = int(counts.get(status, 0)) + 1
                        continue
                    lines.append(line)
                    with _tool_state_lock:
                        _running_tasks[tool_id]["output"] = "".join(lines)
                proc.stdout.close()
                proc.wait()
                with _tool_state_lock:
                    _running_processes.pop(tool_id, None)
                    task = _running_tasks[tool_id]
                    if task["status"] == "cancelling":
                        task.update({"status": "cancelled", "cancellable": False})
                        return
                    if proc.returncode != 0:
                        task.update({"status": "error", "output": "".join(lines), "cancellable": False})
                        return
            if on_success is not None:
                post_step_output = on_success()
                if post_step_output:
                    lines.append(post_step_output.rstrip() + "\n")
            if any("sync" in command for command in tool_commands):
                try:
                    checkpoint = create_local_recovery_checkpoint("sync")
                    lines.append(checkpoint["message"].rstrip() + "\n")
                except Exception as exc:  # noqa: BLE001 - sync itself succeeded.
                    lines.append(f"Local recovery checkpoint failed: {exc}\n")
            clear_home_caches()
            with _tool_state_lock:
                _running_tasks[tool_id].update(
                    {"status": "done", "output": "".join(lines), "cancellable": False}
                )
        except Exception as exc:
            with _tool_state_lock:
                task = _running_tasks.setdefault(tool_id, {})
                task.update({"status": "error", "output": str(exc), "cancellable": False})
        finally:
            with _tool_state_lock:
                _running_processes.pop(tool_id, None)
                if _active_tool_id == tool_id:
                    _active_tool_id = None

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}


def _cancel_tool(tool_id: str) -> dict[str, Any]:
    with _tool_state_lock:
        task = _running_tasks.get(tool_id)
        if not task or task.get("status") not in {"running", "cancelling"}:
            return {"status": task.get("status", "idle") if task else "idle"}
        task["status"] = "cancelling"
        task["cancellable"] = False
        process = _running_processes.get(tool_id)
    if process and process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            process.terminate()
    return {"status": "cancelling"}
