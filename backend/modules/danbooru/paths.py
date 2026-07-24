"""Where a file may live, and where its sidecars go.

Moved verbatim from ``core.py``. Resolves a folder selector to a real directory,
refuses any path outside the data root or a registered library root, and builds
the canonical sidecar locations that must travel with a moved file.

This is Danbooru's path policy. The Files base has its own containment rules in
``files_base/serving.py``; the two are not merged while their managed-root
concepts still differ. No ``core`` import.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException

from config import DATA_ROOT, SIDECAR_DIR
from modules.danbooru.folder_registry import library_roots, registered_folder_rows
from storage_layout import (
    canonical_sidecar_path as layout_sidecar_path,
    sidecar_candidates as layout_sidecar_candidates,
)


def registered_folder_path(folder_name: str) -> Path | None:
    with get_user_db() as uconn:
        row = uconn.execute(
            """SELECT path FROM registered_folders
                WHERE root_id=? OR name=? OR display_name=?
                ORDER BY CASE WHEN root_id=? THEN 0 WHEN name=? THEN 1 ELSE 2 END
                LIMIT 1""",
            (folder_name, folder_name, folder_name, folder_name, folder_name),
        ).fetchone()
    if row and row["path"]:
        return Path(row["path"])
    return None


def ensure_managed_path(path: Path, action: str) -> None:
    """Allow file operations inside the data root or any registered folder."""
    resolved = path.resolve(strict=False)
    roots = [DATA_ROOT.resolve(strict=False)]
    for row in registered_folder_rows():
        if row["path"]:
            roots.append(Path(row["path"]).resolve(strict=False))
    for root in roots:
        try:
            resolved.relative_to(root)
            return
        except ValueError:
            continue
    raise HTTPException(400, f"Refusing to {action} a file outside the library folders")


def folder_target(folder: str) -> tuple[Path, str | None]:
    name = folder.strip().strip("/\\")
    if not name or name.lower() == "root":
        return DATA_ROOT, None

    root_selector_prefix = "@root/"
    if name.startswith(root_selector_prefix):
        root_id = name[len(root_selector_prefix):]
        if not root_id or "/" in root_id or "\\" in root_id:
            raise HTTPException(400, "Invalid library root identity")
        with get_user_db() as uconn:
            row = uconn.execute(
                """SELECT COALESCE(NULLIF(display_name, ''), name) AS display_name, path
                     FROM registered_folders WHERE root_id=?""",
                (root_id,),
            ).fetchone()
        if not row or not row.get("path"):
            raise HTTPException(404, "Registered folder was not found")
        return Path(row["path"]).resolve(strict=False), str(row["display_name"])

    candidate = Path(name)
    if candidate.is_absolute() or candidate.drive or any(part in ("", ".", "..") for part in candidate.parts):
        raise HTTPException(400, "Invalid folder name")

    # Registered folders may live outside the data root; map the folder label
    # (registered name, optionally with a subpath) onto the registered path.
    base_path = registered_folder_path(name)
    subpath = Path()
    if base_path is None and len(candidate.parts) > 1:
        base_path = registered_folder_path(candidate.parts[0])
        subpath = Path(*candidate.parts[1:])
    if base_path is not None:
        resolved_base = base_path.resolve(strict=False)
        resolved_root = DATA_ROOT.resolve(strict=False)
        try:
            resolved_base.relative_to(resolved_root)
        except ValueError:
            target_dir = (resolved_base / subpath).resolve(strict=False)
            try:
                target_dir.relative_to(resolved_base)
            except ValueError:
                raise HTTPException(400, "Target folder must stay inside the registered folder")
            return target_dir, name

    target_dir = (DATA_ROOT / candidate).resolve(strict=False)
    try:
        relative_folder = str(target_dir.relative_to(DATA_ROOT.resolve(strict=False)))
    except ValueError:
        raise HTTPException(400, "Target folder must be inside the data root")

    return target_dir, relative_folder


def central_sidecar_path(media_path: Path, suffix: str) -> Path:
    return layout_sidecar_path(media_path, suffix, DATA_ROOT, SIDECAR_DIR, library_roots())


def sidecar_candidates(media_path: Path, suffix: str) -> list[Path]:
    return layout_sidecar_candidates(media_path, suffix, DATA_ROOT, SIDECAR_DIR, library_roots())


def move_payload_text(payload_text: str | None, target_path: Path) -> str | None:
    if not payload_text:
        return None
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return None

    local_file = payload.setdefault("local_file", {})
    if isinstance(local_file, dict):
        local_file["path"] = str(target_path)
        local_file["name"] = target_path.name
        try:
            local_file["size"] = target_path.stat().st_size
        except OSError:
            pass
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def rewrite_json_sidecar(sidecar_path: Path, target_path: Path) -> str | None:
    if not sidecar_path.exists():
        return None
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    local_file = payload.setdefault("local_file", {})
    if isinstance(local_file, dict):
        local_file["path"] = str(target_path)
        local_file["name"] = target_path.name
        local_file["size"] = target_path.stat().st_size
    sidecar_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)
