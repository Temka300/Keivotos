"""Read-only filesystem browsing for the Files base folder picker (V1.1.0).

Lets the UI navigate the local machine's directory tree to *pick* a folder to
register, instead of typing an absolute path. Lists directory names only — never
file contents — and is reachable only over the loopback, host-validated API.
Isolated: no Danbooru or ``core`` imports.
"""
from __future__ import annotations

import string
import subprocess
import sys
from pathlib import Path


def native_pick_folder(code_root: Path) -> str | None:
    """Open the native Windows folder dialog; return the chosen path or None.

    Reuses the exact helper Danbooru uses (``scripts/windows_folder_picker.py``,
    the COM ``IFileOpenDialog``), so the base and the module pick folders the
    same way. The caller must ensure this is Windows.
    """
    helper = code_root / "scripts" / "windows_folder_picker.py"
    if not helper.is_file():
        raise RuntimeError(f"Windows folder picker helper missing: {helper}")
    command = (
        [sys.executable, "--folder-picker"]
        if getattr(sys, "frozen", False)
        else [sys.executable, str(helper)]
    )
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("folder picker timed out") from exc
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "").strip()[:300] or "unknown error")
    chosen = (result.stdout or "").strip()
    return str(Path(chosen)) if chosen else None


def _drives() -> list[dict[str, str]]:
    if sys.platform == "win32":
        return [
            {"name": f"{letter}:", "path": f"{letter}:\\"}
            for letter in string.ascii_uppercase
            if Path(f"{letter}:\\").exists()
        ]
    return [{"name": "/", "path": "/"}]


def list_directories(path: str) -> dict[str, object]:
    """List sub-directories (or locations if empty); propagate unreadable paths."""
    if not path:
        return {"path": "", "parent": None, "is_root": True, "entries": _drives()}

    current = Path(path).expanduser().resolve(strict=False)
    entries: list[dict[str, str]] = []
    for child in sorted(current.iterdir(), key=lambda item: item.name.casefold()):
        try:
            if child.is_dir() and not child.name.startswith("."):
                entries.append({"name": child.name, "path": str(child)})
        except OSError:
            continue

    # A drive/filesystem root's parent is itself; expose "" so the UI can step up
    # to the drive list.
    parent = "" if current.parent == current else str(current.parent)
    return {"path": str(current), "parent": parent, "is_root": False, "entries": entries}
