"""Running the gallery-dl pipeline as a subprocess: commands, state, progress.

Originally extracted from ``core.py``. Owns subprocess tasks, progress,
cancellation and post-success recovery. Maintenance reservations and locks are
shared through ``maintenance`` so suite backup/restore need not import Danbooru.
The task registry and its lock aliases retain their original object identity.
"""
from __future__ import annotations

import copy
import base64
import json
import logging
import os
import subprocess
import sys
import threading
import traceback
from collections import deque
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
import maintenance
from maintenance import (
    _tool_state_lock, _tool_operation_lock, active_tool_id, exclusive_tool_operation,
)
from modules.danbooru.credentials import credential_environment
from local_recovery import create_local_recovery_checkpoint
from modules.danbooru.folder_registry import registered_folder_rows
from modules.danbooru.home import clear_home_caches
from runtime_logging import redact_log_text


# Resolved against the code root rather than this file's location: the old
# `__file__`-relative form silently required living one level below the root.
SCRIPT_PATH = CODE_ROOT / "scripts" / "danbooru_gallery_dl.py"
PROJECT_ROOT = DATA_ROOT
TOOL_WORKING_DIRECTORY = SCRIPT_PATH.parent.parent

_running_tasks: dict[str, dict[str, Any]] = {}
_running_processes: dict[str, subprocess.Popen[str]] = {}
_logger = logging.getLogger("keivotos.danbooru.jobs")
def tool_task_snapshot(tool_id: str) -> dict[str, Any] | None:
    """Return request-safe task state while the worker may still be updating it."""
    with _tool_state_lock:
        task = _running_tasks.get(tool_id)
        return copy.deepcopy(task) if task is not None else None


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
        "import-finalize", "--output", str(DATA_DB_PATH), "--no-raw-json", "--report-incomplete",
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
    incomplete_steps: set[int] | None = None,
) -> dict[str, Any]:
    with _tool_operation_lock:
        if maintenance._module_transition:
            return {"status": "busy", "active_tool_id": "module-transition"}
        with _tool_state_lock:
            if maintenance._active_tool_id:
                status = "already_running" if maintenance._active_tool_id == tool_id else "busy"
                return {"status": status, "active_tool_id": maintenance._active_tool_id}
            maintenance._active_tool_id = tool_id
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
                "result_counts": {"matched": 0, "partial": 0, "no_match": 0, "error": 0},
            }

    def _run():
        secrets: tuple[str, ...] = ()
        incomplete = False
        try:
            child_environment = environment if environment is not None else credential_environment()
            username = child_environment.get("DANBOORU_USERNAME", "")
            api_key = child_environment.get("DANBOORU_API_KEY", "")
            secrets = (api_key,)
            if username and api_key:
                secrets += (base64.b64encode(f"{username}:{api_key}".encode()).decode(),)
            _logger.info("%s: started (%d steps)", tool_id, len(tool_commands))
            # Keep only the console tail exposed to Settings. A 40k-file import
            # must not retain every subprocess line for the lifetime of the job.
            lines: deque[str] = deque(maxlen=100)
            for step_index, cmd in enumerate(tool_commands, 1):
                with _tool_state_lock:
                    task = _running_tasks[tool_id]
                    if task["status"] == "cancelling":
                        task["status"] = "cancelled"
                        _logger.info("%s: cancelled before the next step", tool_id)
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
                _logger.info("%s: %s", tool_id, stage)
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(TOOL_WORKING_DIRECTORY),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=child_environment,
                )
                with _tool_state_lock:
                    _running_processes[tool_id] = proc
                assert proc.stdout is not None
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    if not line.startswith("FILE_STATUS:"):
                        line = redact_log_text(line, secrets)
                    if line.startswith("STAGE:"):
                        _logger.info("%s: stage %s", tool_id, line.strip().split(":", 1)[1])
                        with _tool_state_lock:
                            value = line.strip().split(":", 1)[1]
                            _running_tasks[tool_id]["stage"] = {
                                "discover": "Finding files", "enrich": "Reading file information",
                                "metadata": "Fetching Danbooru tags", "finalize": "Updating library",
                            }.get(value, value.replace("_", " ").title())
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
                            _logger.warning("%s: ignored malformed file progress", tool_id)
                            continue
                        if not isinstance(event, dict):
                            _logger.warning("%s: ignored non-object file progress", tool_id)
                            continue
                        event = {key: redact_log_text(value, secrets) if isinstance(value, str) else value
                                 for key, value in event.items()}
                        filename = str(event.get("filename") or Path(str(event.get("path") or "")).name)
                        status = str(event.get("status") or "working")
                        with _tool_state_lock:
                            task = _running_tasks[tool_id]
                            task["current_file"] = filename or None
                            task["current_file_path"] = str(event.get("path") or "") or None
                            task["current_file_status"] = status
                            if status in {"matched", "partial", "no_match", "error"}:
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
                        if status in {"matched", "partial", "no_match", "error"}:
                            level = logging.ERROR if status == "error" else logging.WARNING if status == "partial" else logging.INFO
                            _logger.log(level, "%s: %s | %s | %s", tool_id, filename,
                                        status, str(event.get("detail") or ""))
                        continue
                    lines.append(line)
                    message = line.rstrip()
                    if message:
                        level = (logging.ERROR if message.startswith("ERROR:") else
                                 logging.WARNING if message.startswith("WARNING:") else logging.INFO)
                        _logger.log(level, "%s: %s", tool_id, message)
                    with _tool_state_lock:
                        _running_tasks[tool_id]["output"] = "".join(lines)
                proc.stdout.close()
                proc.wait()
                with _tool_state_lock:
                    _running_processes.pop(tool_id, None)
                    task = _running_tasks[tool_id]
                    if task["status"] == "cancelling":
                        task.update({"status": "cancelled", "cancellable": False})
                        _logger.info("%s: cancelled", tool_id)
                        return
                    if proc.returncode != 0:
                        if proc.returncode == 3 and step_index in (incomplete_steps or set()):
                            incomplete = True
                            _logger.warning("%s: some items need attention; preserving successful results", tool_id)
                            continue
                        task.update({"status": "error", "output": "".join(lines), "cancellable": False})
                        _logger.error("%s: %s failed (exit %s); results: %s", tool_id,
                                      stage, proc.returncode, task["result_counts"])
                        return
            if on_success is not None:
                post_step_output = on_success()
                if post_step_output:
                    post_step_output = redact_log_text(post_step_output.rstrip(), secrets)
                    lines.append(post_step_output + "\n")
                    _logger.info("%s: %s", tool_id, post_step_output)
            if any("sync" in command for command in tool_commands):
                try:
                    checkpoint = create_local_recovery_checkpoint("sync")
                    lines.append(checkpoint["message"].rstrip() + "\n")
                    _logger.info("%s: %s", tool_id, checkpoint["message"])
                except Exception as exc:  # noqa: BLE001 - sync itself succeeded.
                    message = redact_log_text(f"Local recovery checkpoint failed: {exc}", secrets)
                    lines.append(message + "\n")
                    _logger.warning("%s: %s", tool_id, message)
            clear_home_caches()
            with _tool_state_lock:
                _running_tasks[tool_id].update(
                    {"status": "partial" if incomplete else "done", "output": "".join(lines), "cancellable": False}
                )
                counts = dict(_running_tasks[tool_id]["result_counts"])
            _logger.info("%s: completed; results: %s", tool_id, counts)
        except Exception as exc:
            _logger.error("%s: unexpected worker failure\n%s", tool_id,
                          redact_log_text(traceback.format_exc(), secrets))
            with _tool_state_lock:
                task = _running_tasks.setdefault(tool_id, {})
                task.update({"status": "error", "output": redact_log_text(str(exc), secrets), "cancellable": False})
        finally:
            with _tool_state_lock:
                _running_processes.pop(tool_id, None)
                if maintenance._active_tool_id == tool_id:
                    maintenance._active_tool_id = None

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
