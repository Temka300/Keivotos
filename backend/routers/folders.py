from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from config import (
    ARTIST_PROFILE_ARCHIVE_DIR,
    CODE_ROOT,
    DEFAULT_BACKUP_DIR,
    GALLERY_DL_DIR,
    LOG_DIR,
    METADATA_DIR,
    MODULE_HOME,
    SIDECAR_DIR,
    SUITE_HOME,
    THUMB_DIR,
)
from core import *  # shared query, database, and media helpers
from models import (
    FolderRelocate,
    FolderRelocateResult,
    FolderRemovalPreview,
    FolderRemovalResult,
)
from storage_layout import LibraryRoot, current_sidecar_files_for_root, new_root_id

router = APIRouter()

FolderRemovalMode = Literal["unindex_only", "delete_sidecars"]


def _is_generated_folder(folder_path: Path) -> bool:
    """Protect generated data without blocking library roots beside it."""
    resolved_metadata = METADATA_DIR.resolve(strict=False)
    resolved_module = MODULE_HOME.resolve(strict=False)
    resolved_suite = SUITE_HOME.resolve(strict=False)
    if folder_path == resolved_suite or folder_path in resolved_module.parents:
        return True
    if resolved_metadata != resolved_module:
        return (
            folder_path == resolved_metadata
            or resolved_metadata in folder_path.parents
            or folder_path in resolved_metadata.parents
        )
    if folder_path == resolved_metadata:
        return True
    generated_paths = (
        ARTIST_PROFILE_ARCHIVE_DIR,
        DEFAULT_BACKUP_DIR,
        GALLERY_DL_DIR,
        LOG_DIR,
        SUITE_HOME / "backups",
        METADATA_DIR / "local_recovery",
        METADATA_DIR / "sidecar_archive",
        SIDECAR_DIR,
        THUMB_DIR,
    )
    return any(
        folder_path == generated.resolve(strict=False)
        or generated.resolve(strict=False) in folder_path.parents
        for generated in generated_paths
    )


def _unsafe_library_root_reason(folder_path: Path) -> str | None:
    anchor = Path(folder_path.anchor).resolve(strict=False) if folder_path.anchor else None
    if anchor is not None and folder_path == anchor:
        return "Register a specific image folder, not an entire drive or filesystem root"
    if _is_generated_folder(folder_path):
        return "Cannot register Keivotos metadata, backups, logs, or work folders"
    return None


def _registered_folder_row(identifier: str) -> dict | None:
    with get_user_db() as connection:
        return connection.execute(
            """SELECT name AS registration_key,
                      COALESCE(NULLIF(display_name, ''), name) AS name,
                      path, root_id
                 FROM registered_folders
                WHERE root_id=? OR name=?
                ORDER BY CASE WHEN root_id=? THEN 0 ELSE 1 END
                LIMIT 1""",
            (identifier, identifier, identifier),
        ).fetchone()


def _indexed_folder_rows(folder_name: str, root_id: str | None) -> list[dict]:
    prefix = folder_name + os.sep
    with get_data_db() as connection:
        rows = connection.execute(
            "SELECT id, path, folder, root_id FROM files WHERE folder IS NOT NULL OR root_id IS NOT NULL"
        ).fetchall()
    return [
        row for row in rows
        if (
            row.get("root_id") == root_id
            if root_id
            else row.get("folder") == folder_name
            or str(row.get("folder") or "").startswith(prefix)
        )
    ]


def _folder_removal_details(folder_name: str) -> tuple[dict, list[dict], list[Path]]:
    registered = _registered_folder_row(folder_name)
    if not registered or not registered.get("path") or not registered.get("root_id"):
        raise HTTPException(404, "Registered folder was not found")
    rows = _indexed_folder_rows(folder_name, str(registered["root_id"]))
    root = LibraryRoot(
        str(registered["root_id"]),
        str(registered["name"]),
        Path(str(registered["path"])).expanduser().resolve(strict=False),
    )
    try:
        sidecars = current_sidecar_files_for_root(
            root,
            [Path(str(row["path"])) for row in rows],
            DATA_ROOT,
            SIDECAR_DIR,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return registered, rows, sidecars


def _remove_index_rows(folder_name: str, rows: list[dict]) -> int:
    removed_ids = [int(row["id"]) for row in rows]
    removed_paths = [str(row["path"]) for row in rows]
    with get_data_db() as conn:
        for start in range(0, len(removed_ids), 400):
            chunk = removed_ids[start:start + 400]
            placeholders = ",".join("?" for _ in chunk)
            conn.execute(
                f"""DELETE FROM post_tags WHERE post_id IN (
                        SELECT id FROM posts WHERE file_id IN ({placeholders}))""",
                chunk,
            )
            conn.execute(f"DELETE FROM posts WHERE file_id IN ({placeholders})", chunk)
            conn.execute(f"DELETE FROM files WHERE id IN ({placeholders})", chunk)
        if removed_ids:
            conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM post_tags)")
        for table in ("sync_manifest", "ingest_state"):
            try:
                for start in range(0, len(removed_paths), 400):
                    chunk = removed_paths[start:start + 400]
                    placeholders = ",".join("?" for _ in chunk)
                    conn.execute(f"DELETE FROM {table} WHERE media_path IN ({placeholders})", chunk)
            except sqlite3.OperationalError:
                pass  # Compatibility with older databases.
        conn.commit()
    with get_user_db() as uconn:
        uconn.execute(
            "DELETE FROM registered_folders WHERE root_id=? OR name=?",
            (folder_name, folder_name),
        )
        uconn.commit()
    return len(removed_ids)


def _delete_current_sidecars(sidecars: list[Path]) -> tuple[int, int]:
    sidecar_base = SIDECAR_DIR.resolve(strict=False)
    removed = removed_bytes = 0
    parent_candidates: set[Path] = set()
    for path in sidecars:
        resolved = path.resolve(strict=False)
        if resolved == sidecar_base or sidecar_base not in resolved.parents:
            raise HTTPException(400, "Refused to remove a sidecar outside the metadata directory")
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
            path.unlink()
        except OSError as exc:
            raise HTTPException(500, f"Could not remove sidecar: {path.name}") from exc
        removed += 1
        removed_bytes += size
        parent_candidates.add(path.parent)

    for initial in sorted(parent_candidates, key=lambda item: len(item.parts), reverse=True):
        parent = initial
        while parent != sidecar_base and sidecar_base in parent.resolve(strict=False).parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    return removed, removed_bytes


@router.get("/api/folders", response_model=list[FolderInfo])
def list_folders():
    with get_data_db() as conn:
        rows = conn.execute(
            """SELECT root_id, COALESCE(folder, 'root') as name, COUNT(*) as count
               FROM files GROUP BY root_id, folder ORDER BY count DESC"""
        ).fetchall()

    registered_rows = registered_folder_rows()
    registered_ids = {str(row["root_id"]) for row in registered_rows if row.get("root_id")}
    indexed_by_root: dict[str, int] = {}
    unregistered: dict[str, int] = {}
    for row in rows:
        root_id = str(row.get("root_id") or "")
        if root_id in registered_ids:
            indexed_by_root[root_id] = indexed_by_root.get(root_id, 0) + int(row["count"])
        else:
            name = str(row["name"])
            unregistered[name] = unregistered.get(name, 0) + int(row["count"])

    result = [
        FolderInfo(
            name=str(row["name"]),
            selector=f"@root/{row['root_id']}",
            count=indexed_by_root.get(str(row["root_id"]), 0),
            path=str(row["path"]) if row.get("path") else None,
            root_id=str(row["root_id"]),
            registered=True,
        )
        for row in registered_rows
        if row.get("root_id")
    ]
    result.extend(
        FolderInfo(name=name, selector=name, count=count)
        for name, count in unregistered.items()
    )
    return sorted(result, key=lambda folder: (-folder.count, folder.name.casefold(), folder.path or ""))


@router.post("/api/folders")
def register_folder(data: FolderCreate):
    raw = data.path.strip().strip('"')
    if not raw:
        raise HTTPException(400, "Folder path is required")
    folder_path = Path(raw).expanduser()
    if not folder_path.is_absolute():
        folder_path = DATA_ROOT / folder_path
    folder_path = folder_path.resolve(strict=False)
    if not folder_path.is_dir():
        raise HTTPException(400, f"Folder does not exist: {folder_path}")

    resolved_root = DATA_ROOT.resolve(strict=False)
    if folder_path == resolved_root:
        raise HTTPException(400, "Register individual image folders, not the data root itself")
    unsafe_reason = _unsafe_library_root_reason(folder_path)
    if unsafe_reason:
        raise HTTPException(400, unsafe_reason)

    try:
        name = str(folder_path.relative_to(resolved_root))
    except ValueError:
        name = folder_path.name

    normalized_path = os.path.normcase(str(folder_path))
    for row in registered_folder_rows():
        if row.get("path") and os.path.normcase(str(Path(row["path"]).resolve(strict=False))) == normalized_path:
            raise HTTPException(409, "This exact folder is already registered")

    root_id = new_root_id()

    with get_user_db() as uconn:
        uconn.execute(
            """INSERT INTO registered_folders (name, path, root_id, display_name)
               VALUES (?, ?, ?, ?)""",
            (root_id, str(folder_path), root_id, name),
        )
        uconn.commit()

    sync = _start_folder_import([str(folder_path)])
    return {
        "status": "registered",
        "name": name,
        "selector": f"@root/{root_id}",
        "path": str(folder_path),
        "root_id": root_id,
        "sync": sync["status"],
        "active_tool_id": sync.get("active_tool_id"),
    }


@router.post("/api/folders/browse")
def browse_for_folder():
    """Open the native Windows IFileOpenDialog folder picker."""
    if os.name != "nt":
        raise HTTPException(
            501,
            "The folder picker is available only on Windows; enter the path manually",
        )

    picker_helper = CODE_ROOT / "scripts" / "windows_folder_picker.py"
    if not picker_helper.is_file():
        raise HTTPException(500, f"Packaged Windows folder picker is missing: {picker_helper}")

    picker_command = (
        [sys.executable, "--folder-picker"]
        if getattr(sys, "frozen", False)
        else [sys.executable, str(picker_helper)]
    )
    try:
        result = subprocess.run(
            picker_command,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "Folder picker timed out")
    if result.returncode != 0:
        detail = (result.stderr or "").strip()[:300]
        raise HTTPException(500, f"Windows folder picker failed: {detail or 'unknown error'}")
    chosen = (result.stdout or "").strip()
    return {"path": str(Path(chosen)) if chosen else None}


@router.post("/api/folders/{folder_identifier}/rescan")
def rescan_folder(folder_identifier: str):
    path = registered_folder_path(folder_identifier)
    if path is None:
        candidate = (DATA_ROOT / folder_identifier).resolve(strict=False)
        try:
            candidate.relative_to(DATA_ROOT.resolve(strict=False))
        except ValueError as exc:
            raise HTTPException(400, "Folder must stay inside the data root") from exc
        if not candidate.is_dir():
            raise HTTPException(404, "Folder not found")
        path = candidate
    return _start_folder_import([str(path)])


@router.put("/api/folders/{root_id}/path", response_model=FolderRelocateResult)
def relocate_folder(root_id: str, data: FolderRelocate):
    """Point a stable root identity at a folder that the user moved on disk."""
    running_tool = active_tool_id()
    if running_tool is not None:
        raise HTTPException(409, f"Wait for {running_tool} to finish before relocating a folder")

    registered = _registered_folder_row(root_id)
    if not registered or str(registered.get("root_id") or "") != root_id:
        raise HTTPException(404, "Registered folder was not found")

    raw = data.path.strip().strip('"')
    if not raw:
        raise HTTPException(400, "Folder path is required")
    new_root = Path(raw).expanduser()
    if not new_root.is_absolute():
        raise HTTPException(400, "The relocated folder must use an absolute path")
    new_root = new_root.resolve(strict=False)
    if not new_root.is_dir():
        raise HTTPException(400, f"Folder does not exist: {new_root}")
    if new_root == DATA_ROOT.resolve(strict=False):
        raise HTTPException(400, "Register individual image folders, not the data root itself")
    unsafe_reason = _unsafe_library_root_reason(new_root)
    if unsafe_reason:
        raise HTTPException(400, unsafe_reason)

    normalized_new_root = os.path.normcase(str(new_root))
    for row in registered_folder_rows():
        if str(row.get("root_id") or "") == root_id or not row.get("path"):
            continue
        if os.path.normcase(str(Path(row["path"]).resolve(strict=False))) == normalized_new_root:
            raise HTTPException(409, "This exact folder is already registered as another root")

    old_root = Path(str(registered["path"])).expanduser().resolve(strict=False)
    display_name = new_root.name or str(registered["name"])

    with get_data_db() as conn:
        root_rows = conn.execute(
            "SELECT id, path, relative_path FROM files WHERE root_id=? ORDER BY id",
            (root_id,),
        ).fetchall()
        path_updates: list[tuple[int, str, str]] = []
        seen_targets: set[str] = set()
        for row in root_rows:
            relative = Path(str(row.get("relative_path") or ""))
            if not str(relative) or relative.is_absolute() or ".." in relative.parts:
                try:
                    relative = Path(str(row["path"])).resolve(strict=False).relative_to(old_root)
                except ValueError as exc:
                    raise HTTPException(409, f"Indexed file is not inside the old root: {row['path']}") from exc
            new_path = (new_root / relative).resolve(strict=False)
            try:
                new_path.relative_to(new_root)
            except ValueError as exc:
                raise HTTPException(400, "Indexed relative path escapes the relocated root") from exc
            normalized_target = os.path.normcase(str(new_path))
            occupied = conn.execute(
                "SELECT id, root_id FROM files WHERE path=? AND id<>?",
                (str(new_path), int(row["id"])),
            ).fetchone()
            if occupied is not None and str(occupied.get("root_id") or "") != root_id:
                raise HTTPException(409, f"The new root conflicts with an indexed path: {new_path}")
            if normalized_target in seen_targets:
                raise HTTPException(409, f"Two indexed files resolve to the same relocated path: {new_path}")
            seen_targets.add(normalized_target)
            path_updates.append((int(row["id"]), str(row["path"]), str(new_path)))

        conn.execute("ATTACH DATABASE ? AS userdb", (str(USER_DB_PATH),))
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """UPDATE userdb.registered_folders
                      SET path=?, display_name=?
                    WHERE root_id=?""",
                (str(new_root), display_name, root_id),
            )
            old_paths = {old_path for _, old_path, _ in path_updates}
            for _, _, new_path in path_updates:
                if new_path in old_paths:
                    continue
                # These are regenerable index rows. A stale entry at the new
                # location must not block preservation of the stable file/root IDs.
                for table in ("sync_manifest", "ingest_state"):
                    try:
                        conn.execute(f"DELETE FROM {table} WHERE media_path=?", (new_path,))
                    except sqlite3.OperationalError:
                        pass
            for file_id, old_path, new_path in path_updates:
                relative_parent = Path(new_path).relative_to(new_root).parent
                folder_label = (
                    display_name
                    if str(relative_parent) == "."
                    else str(Path(display_name) / relative_parent)
                )
                conn.execute(
                    "UPDATE files SET path=?, folder=? WHERE id=?",
                    (new_path, folder_label, file_id),
                )
                for table in ("sync_manifest", "ingest_state"):
                    try:
                        conn.execute(
                            f"UPDATE {table} SET media_path=? WHERE media_path=?",
                            (new_path, old_path),
                        )
                    except sqlite3.OperationalError:
                        pass
                for table in ("favorites", "collection_items", "user_image_tags", "image_views", "tag_removals"):
                    conn.execute(
                        f"UPDATE userdb.{table} SET file_path=? WHERE file_id=? OR file_path=?",
                        (new_path, file_id, old_path),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.execute("DETACH DATABASE userdb")

    sync = _start_folder_import([str(new_root)])
    return FolderRelocateResult(
        status="relocated",
        name=display_name,
        selector=f"@root/{root_id}",
        path=str(new_root),
        root_id=root_id,
        files_updated=len(path_updates),
        sync=sync["status"],
        active_tool_id=sync.get("active_tool_id"),
    )


@router.get("/api/folders/{folder_identifier}/removal-preview", response_model=FolderRemovalPreview)
def folder_removal_preview(folder_identifier: str):
    registered, rows, sidecars = _folder_removal_details(folder_identifier)
    sidecar_bytes = 0
    for path in sidecars:
        try:
            sidecar_bytes += path.stat().st_size
        except OSError:
            continue
    return FolderRemovalPreview(
        name=str(registered["name"]),
        path=str(registered["path"]),
        root_id=str(registered["root_id"]),
        indexed_files=len(rows),
        sidecar_files=len(sidecars),
        sidecar_bytes=sidecar_bytes,
    )


@router.delete("/api/folders/{folder_identifier}", response_model=FolderRemovalResult)
def remove_folder(
    folder_identifier: str,
    mode: FolderRemovalMode = Query(default="unindex_only"),
):
    running_tool = active_tool_id()
    if running_tool is not None:
        raise HTTPException(409, f"Wait for {running_tool} to finish before removing a folder")

    registered, rows, sidecars = _folder_removal_details(folder_identifier)
    sidecar_files_removed = sidecar_bytes_removed = 0
    if mode == "delete_sidecars":
        sidecar_files_removed, sidecar_bytes_removed = _delete_current_sidecars(sidecars)

    files_removed = _remove_index_rows(folder_identifier, rows)
    return FolderRemovalResult(
        status="removed",
        name=str(registered["name"]),
        mode=mode,
        files_removed=files_removed,
        sidecar_files_removed=sidecar_files_removed,
        sidecar_bytes_removed=sidecar_bytes_removed,
    )
