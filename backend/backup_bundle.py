"""Manual, user-directed metadata backup bundles and validated restoration."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
import time
import zipfile
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from database_connections import exclusive_database_access
from files_base import attachment_store
from module_descriptor import BackupComponent

from config import (
    MODULE_REGISTRY,
    ARTIST_PROFILE_ARCHIVE_DIR,
    DATA_DB_PATH,
    METADATA_DIR,
    SIDECAR_DIR,
    USER_DB_PATH,
    get_backup_config,
    runtime_config_snapshot,
    save_config,
)


BACKUP_FORMAT_VERSION = 1
BACKUP_FORMAT = "danbooru-metadata-backup"
BACKUP_SUFFIX = ".keivotosbk"
LEGACY_BACKUP_SUFFIXES = (".whbackup",)
SUPPORTED_BACKUP_SUFFIXES = (BACKUP_SUFFIX, *LEGACY_BACKUP_SUFFIXES)
# Until restore dispatch is generalized, reject unsupported declarations before
# touching live data rather than silently dropping their contents.
_LEGACY_RESTORE_KEYS = frozenset({
    "user_database", "library_database", "sidecars", "sidecar_history",
    "artist_profile_archive", "file_attachments",
})


def collect_backup_components(registry=MODULE_REGISTRY) -> dict[str, BackupComponent]:
    """Collect installed owners without consulting enabled state or running hooks."""
    declarations = [BackupComponent("user_database", "suite", "databases/user.sqlite", "sqlite", USER_DB_PATH)]
    for descriptor in registry:
        for component in descriptor.backup_components():
            if component.owner != descriptor.slug:
                raise ValueError("Backup component owner does not match its descriptor")
            declarations.append(component)
    result = {}
    roots = []
    for component in declarations:
        path = PurePosixPath(component.archive_name)
        if (not re.fullmatch(r"[a-z][a-z0-9_]*", component.key) or component.key in result
                or not component.archive_name or not path.parts or ":" in component.archive_name
                or path.is_absolute() or ".." in path.parts or "\\" in component.archive_name
                or path.as_posix() != component.archive_name or path.parts[0] in {"config.json", "manifest.json"}):
            raise ValueError(f"Invalid or duplicate backup component: {component.key}")
        if component.kind not in {"sqlite", "tree", "attachments"}:
            raise ValueError(f"Unsupported backup component kind: {component.kind}")
        if component.kind != "attachments" and component.source is None:
            raise ValueError(f"Backup source missing: {component.key}")
        if component.kind == "attachments" and (component.owner != "files" or component.key != "file_attachments"):
            raise ValueError("Only Files owns the attachment adapter")
        if any(path == other or path in other.parents or other in path.parents for other in roots):
            raise ValueError(f"Overlapping backup archive paths: {component.archive_name}")
        roots.append(path)
        result[component.key] = component
    return result


BACKUP_COMPONENTS = collect_backup_components()
# Compatibility view for the existing restore path and test path overrides.
COMPONENTS = {
    key: (component.archive_name, component.source)
    for key, component in BACKUP_COMPONENTS.items() if component.kind != "attachments"
}
# Files-base attachment bytes live inside the user's own folder (outside the
# metadata tree), keyed by content hash. They are handled specially: bundled by
# hash on backup, and re-materialized additively (create-only) after the atomic
# restore, so the fragile metadata-tree rollback logic is never involved.
ATTACHMENTS_COMPONENT = "file_attachments"
ATTACHMENTS_ARCHIVE_ROOT = BACKUP_COMPONENTS[ATTACHMENTS_COMPONENT].archive_name
_bundle_lock = threading.Lock()
_estimate_cache_lock = threading.Lock()
_estimate_cache: dict[tuple[str, str], tuple[float, int, int]] = {}
_ESTIMATE_CACHE_SECONDS = 60.0


@contextmanager
def _staging_directory(base: Path, name: str):
    """Create a deterministic, crash-recoverable staging directory."""
    resolved_base = base.expanduser().resolve(strict=False)
    resolved_base.mkdir(parents=True, exist_ok=True)
    staging = resolved_base / name
    resolved_staging = staging.resolve(strict=False)
    if resolved_staging.parent != resolved_base:
        raise ValueError("Backup staging directory escaped its configured parent")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        yield staging
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
    elif path.is_dir():
        yield from (item for item in path.rglob("*") if item.is_file())


def _tree_stats(path: Path) -> tuple[int, int]:
    count = size = 0
    for item in _files(path):
        try:
            size += item.stat().st_size
            count += 1
        except OSError:
            continue
    return count, size


def _cached_tree_stats(component: str, path: Path) -> tuple[int, int]:
    """Reuse recent estimate scans; bundle creation still reads every file."""
    key = (component, str(path.resolve(strict=False)))
    now = time.monotonic()
    with _estimate_cache_lock:
        cached = _estimate_cache.get(key)
        if cached and now - cached[0] < _ESTIMATE_CACHE_SECONDS:
            return cached[1], cached[2]
    count, size = _tree_stats(path)
    with _estimate_cache_lock:
        _estimate_cache[key] = (now, count, size)
    return count, size


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def _component_keys() -> tuple[str, ...]:
    return (*COMPONENTS.keys(), ATTACHMENTS_COMPONENT)


def normalized_components(value: dict[str, Any] | None = None) -> dict[str, bool]:
    keys = _component_keys()
    configured = dict(get_backup_config()["components"])
    if value:
        configured.update({key: bool(item) for key, item in value.items() if key in keys})
    return {key: bool(configured.get(key, False)) for key in keys}


def _attachment_arcname(content_hash: str, ext: str) -> str:
    suffix = ("." + ext) if ext else ""
    return f"{content_hash}{suffix}"


def _attachment_records(user_db_path: Path) -> dict[str, Path]:
    """Map ``<hash><ext>`` -> the on-disk attachment file, de-duplicated by hash.

    Reads the attachment rows from ``user_db_path`` read-only and resolves each
    to its byte-store location. Rows whose bytes are missing (e.g. an unplugged
    folder) are skipped. Returns empty for an older user DB without the table.
    """
    path = Path(user_db_path)
    if not path.exists():
        return {}
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        try:
            rows = connection.execute(
                "SELECT content_hash, file_name, media_type, stored_root "
                "FROM files_annotation_attachments WHERE stored_root IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
    finally:
        connection.close()
    records: dict[str, Path] = {}
    for row in rows:
        ext = attachment_store.extension_for(row["file_name"], row["media_type"])
        arcname = _attachment_arcname(row["content_hash"], ext)
        if arcname in records:
            continue
        source = attachment_store.attachment_path(row["stored_root"], row["content_hash"], ext)
        if source.is_file():
            records[arcname] = source
    return records


def _restore_attachments(bundle_dir: Path, user_db_path: Path) -> None:
    """Re-materialize bundled attachment bytes to their recorded store location.

    Additive and create-only: it never overwrites an existing file and never
    deletes anything, so it cannot corrupt the just-completed restore. Each file
    is attempted independently; a missing target drive skips only that file.
    """
    if not bundle_dir.is_dir():
        return
    path = Path(user_db_path)
    if not path.exists():
        return
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        try:
            rows = connection.execute(
                "SELECT content_hash, file_name, media_type, stored_root "
                "FROM files_annotation_attachments WHERE stored_root IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            return
    finally:
        connection.close()
    for row in rows:
        ext = attachment_store.extension_for(row["file_name"], row["media_type"])
        bundled = bundle_dir / _attachment_arcname(row["content_hash"], ext)
        target = attachment_store.attachment_path(row["stored_root"], row["content_hash"], ext)
        if not bundled.is_file() or target.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled, target)
        except OSError:
            continue  # e.g. the stored folder's drive is not present on restore.


def backup_estimate(components: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = normalized_components(components)
    details: dict[str, dict[str, Any]] = {}
    total_files = total_bytes = 0
    for key, (_, path) in COMPONENTS.items():
        count, size = _cached_tree_stats(key, path) if selected[key] else (0, 0)
        details[key] = {
            "owner": BACKUP_COMPONENTS[key].owner,
            "enabled": selected[key],
            "exists": path.exists(),
            "files": count,
            "bytes": size,
            "display_size": _format_bytes(size),
        }
        total_files += count
        total_bytes += size

    # Attachments are sized directly (not a single tree), so the estimate scan
    # count for the tree components stays unchanged.
    attachment_records = _attachment_records(USER_DB_PATH) if selected[ATTACHMENTS_COMPONENT] else {}
    attachment_bytes = 0
    for source in attachment_records.values():
        try:
            attachment_bytes += source.stat().st_size
        except OSError:
            continue
    details[ATTACHMENTS_COMPONENT] = {
        "owner": BACKUP_COMPONENTS[ATTACHMENTS_COMPONENT].owner,
        "enabled": selected[ATTACHMENTS_COMPONENT],
        "exists": bool(attachment_records),
        "files": len(attachment_records),
        "bytes": attachment_bytes,
        "display_size": _format_bytes(attachment_bytes),
    }
    total_files += len(attachment_records)
    total_bytes += attachment_bytes

    # JSON/text/SQLite data usually compresses well; this is deliberately
    # conservative and the completed bundle reports its exact size.
    estimated_compressed = int(total_bytes * 0.45)
    return {
        "components": selected,
        "details": details,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "display_size": _format_bytes(total_bytes),
        "estimated_compressed_bytes": estimated_compressed,
        "estimated_compressed_display": _format_bytes(estimated_compressed),
    }


def backup_configuration() -> dict[str, Any]:
    config = get_backup_config()
    destination = Path(config["destination"]).expanduser()
    return {
        "destination": str(destination),
        "components": normalized_components(config["components"]),
        "estimate": backup_estimate(config["components"]),
        "backups": list_backups(destination),
    }


def update_backup_configuration(components: dict[str, Any]) -> dict[str, Any]:
    selected = normalized_components(components)
    if not any(selected.values()):
        raise ValueError("Select at least one backup component")
    save_config({"backup_components": {**get_backup_config()["components"], **selected}})
    return backup_configuration()


def list_backups(destination: Path | None = None) -> list[dict[str, Any]]:
    target = destination or Path(get_backup_config()["destination"]).expanduser()
    if not target.is_dir():
        return []
    paths = [
        path
        for path in target.iterdir()
        if path.is_file() and path.suffix.casefold() in SUPPORTED_BACKUP_SUFFIXES
    ]
    result = []
    for path in sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            stat = path.stat()
            result.append({
                "name": path.name,
                "path": str(path),
                "bytes": stat.st_size,
                "display_size": _format_bytes(stat.st_size),
                "created_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            })
        except OSError:
            continue
    return result


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Database does not exist: {source}")
    source_connection = sqlite3.connect(source, timeout=60)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.execute("PRAGMA busy_timeout = 60000")
        source_connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    _check_sqlite(destination)


def _check_sqlite(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    if not row or row[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed for {path.name}: {row!r}")


def _write_tree(archive: zipfile.ZipFile, source: Path, archive_root: str) -> int:
    written = 0
    if not source.exists():
        return written
    if source.is_file():
        archive.write(source, archive_root)
        return 1
    for path in _files(source):
        relative = path.relative_to(source).as_posix()
        archive.write(path, f"{archive_root}/{relative}")
        written += 1
    return written


def create_backup_bundle(components: dict[str, Any] | None = None) -> dict[str, Any]:
    if not _bundle_lock.acquire(blocking=False):
        raise RuntimeError("A backup or restore is already running")
    try:
        requested = normalized_components(components)
        selected = dict(requested)
        omitted = []
        for key, (_archive_name, source) in COMPONENTS.items():
            if selected[key] and BACKUP_COMPONENTS[key].owner != "suite" and not source.exists():
                selected[key] = False
                omitted.append(key)
        if not any(selected.values()):
            raise ValueError("Select at least one backup component")
        destination = Path(get_backup_config()["destination"]).expanduser()
        destination.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time())
        final_path = destination / f"backup_{stamp}{BACKUP_SUFFIX}"
        counter = 2
        while final_path.exists():
            final_path = destination / f"backup_{stamp}_{counter}{BACKUP_SUFFIX}"
            counter += 1
        partial_path = final_path.with_name(final_path.name + ".partial")
        partial_path.unlink(missing_ok=True)

        # Stage beside the requested backup destination. The metadata source
        # only needs to be readable, and the staging files stay on the same
        # writable volume as the final bundle.
        with _staging_directory(destination, ".danbooru-backup-staging") as temporary:
            staged: dict[str, Path] = {}
            for key, (_archive_name, source) in COMPONENTS.items():
                if selected[key] and BACKUP_COMPONENTS[key].kind == "sqlite":
                    snapshot = temporary / f"{key}.sqlite"
                    _sqlite_snapshot(source, snapshot)
                    staged[key] = snapshot

            manifest: dict[str, Any] = {
                "format": BACKUP_FORMAT,
                "format_version": BACKUP_FORMAT_VERSION,
                "created_at": datetime.now().astimezone().isoformat(),
                "components": selected,
                "requested_components": requested,
                "component_owners": {key: BACKUP_COMPONENTS[key].owner for key in selected},
                "omitted_components": omitted,
                "external_images_included": False,
                "thumbnails_included": False,
                "credentials_included": False,
                "files": [],
            }
            with zipfile.ZipFile(partial_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
                for key, (archive_name, source) in COMPONENTS.items():
                    if not selected[key]:
                        continue
                    actual_source = staged.get(key, source)
                    _write_tree(archive, actual_source, archive_name)
                if selected[ATTACHMENTS_COMPONENT]:
                    for arcname, source in _attachment_records(USER_DB_PATH).items():
                        archive.write(source, f"{ATTACHMENTS_ARCHIVE_ROOT}/{arcname}")
                sanitized_config = runtime_config_snapshot()
                archive.writestr("config.json", json.dumps(sanitized_config, indent=2, ensure_ascii=False))
                manifest["files"] = [
                    {"path": info.filename, "bytes": info.file_size, "crc": info.CRC}
                    for info in archive.infolist()
                ]
                archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

            with zipfile.ZipFile(partial_path, "r") as verification:
                failed = verification.testzip()
                if failed:
                    raise RuntimeError(f"Backup ZIP verification failed at {failed}")
                parsed_manifest = json.loads(verification.read("manifest.json"))
                if parsed_manifest.get("format_version") != BACKUP_FORMAT_VERSION:
                    raise RuntimeError("Backup manifest verification failed")
            partial_path.replace(final_path)

        return {
            "status": "created",
            "path": str(final_path),
            "name": final_path.name,
            "bytes": final_path.stat().st_size,
            "display_size": _format_bytes(final_path.stat().st_size),
            "components": selected,
            "omitted_components": omitted,
            "message": "Metadata backup created and verified. External images and thumbnails were not copied."
            + (" Unavailable components were omitted: " + ", ".join(key.replace("_", " ") for key in omitted) + "." if omitted else ""),
        }
    finally:
        _bundle_lock.release()


def inspect_backup_bundle(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as archive:
        failed = archive.testzip()
        if failed:
            raise RuntimeError(f"Backup is corrupt at {failed}")
        manifest = json.loads(archive.read("manifest.json"))
        format_version = int(manifest.get("format_version", 0))
        format_name = manifest.get("format")
        compatible_v1 = (
            format_version == 1
            and isinstance(format_name, str)
            and format_name.endswith("-metadata-backup")
            and isinstance(manifest.get("components"), dict)
            and isinstance(manifest.get("files"), list)
        )
        if format_name != BACKUP_FORMAT and not compatible_v1:
            raise ValueError("Not a Danbooru metadata backup")
        if format_version > BACKUP_FORMAT_VERSION:
            raise ValueError("Backup was created by a newer unsupported format")
        return manifest


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = []
    for info in archive.infolist():
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Unsafe backup entry: {info.filename}")
        members.append(info)
    return members


def _quiesce_sqlite(path: Path, rollback_dir: Path) -> None:
    """Checkpoint a live database and preserve any remaining journal files."""
    if not path.exists():
        return
    connection = sqlite3.connect(path, timeout=60)
    try:
        connection.execute("PRAGMA busy_timeout = 60000")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    for suffix in ("-wal", "-shm"):
        companion = Path(str(path) + suffix)
        if companion.exists():
            preserved = rollback_dir / companion.relative_to(METADATA_DIR)
            preserved.parent.mkdir(parents=True, exist_ok=True)
            companion.replace(preserved)


def restore_backup_bundle(name: str) -> dict[str, Any]:
    if not _bundle_lock.acquire(blocking=False):
        raise RuntimeError("A backup or restore is already running")
    try:
        destination = Path(get_backup_config()["destination"]).expanduser().resolve(strict=False)
        source = (destination / Path(name).name).resolve(strict=False)
        try:
            source.relative_to(destination)
        except ValueError as exc:
            raise ValueError("Backup must be inside the configured backup destination") from exc
        if source.suffix.casefold() not in SUPPORTED_BACKUP_SUFFIXES or not source.is_file():
            raise FileNotFoundError("Backup file was not found")

        manifest = inspect_backup_bundle(source)
        declared = manifest.get("components", {})
        unsupported = {key for key, included in declared.items() if included and (key not in _component_keys() or key not in _LEGACY_RESTORE_KEYS)}
        if unsupported:
            raise ValueError("Backup component restore support is unavailable: " + ", ".join(sorted(unsupported)))
        components = normalized_components(declared)
        METADATA_DIR.mkdir(parents=True, exist_ok=True)
        rollback_dir = METADATA_DIR / "local_recovery" / ("restore_" + datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S"))
        rollback_dir.mkdir(parents=True, exist_ok=False)

        with _staging_directory(METADATA_DIR, ".danbooru-restore-staging") as staging:
            with zipfile.ZipFile(source, "r") as archive:
                archive.extractall(staging, members=_safe_members(archive))

            staged_user = staging / "databases" / "user.sqlite"
            staged_library = staging / "databases" / "danbooru.sqlite"
            if components.get("user_database", False):
                _check_sqlite(staged_user)
            if components.get("library_database", False):
                _check_sqlite(staged_library)

            replacements: list[tuple[Path, Path]] = []
            if components.get("user_database", False):
                replacements.append((USER_DB_PATH, staged_user))
            if components.get("library_database", False):
                replacements.append((DATA_DB_PATH, staged_library))
            if components.get("sidecars", False) and (staging / "sidecars").exists():
                replacements.append((SIDECAR_DIR, staging / "sidecars"))
            if components.get("sidecar_history", False) and (staging / "sidecar_archive").exists():
                replacements.append((METADATA_DIR / "sidecar_archive", staging / "sidecar_archive"))
            if components.get("artist_profile_archive", False) and (staging / "artist_profile_archive").exists():
                replacements.append((ARTIST_PROFILE_ARCHIVE_DIR, staging / "artist_profile_archive"))

            with exclusive_database_access():
                applied: list[tuple[Path, Path | None]] = []
                try:
                    if components.get("user_database", False):
                        _quiesce_sqlite(USER_DB_PATH, rollback_dir)
                    if components.get("library_database", False):
                        _quiesce_sqlite(DATA_DB_PATH, rollback_dir)
                    for live, restored in replacements:
                        backup_live = rollback_dir / live.relative_to(METADATA_DIR)
                        if live.exists():
                            backup_live.parent.mkdir(parents=True, exist_ok=True)
                            live.replace(backup_live)
                            previous: Path | None = backup_live
                        else:
                            previous = None
                        # Record the rollback point before installing the restored
                        # item. If that move itself fails, the original still has
                        # to be put back.
                        applied.append((live, previous))
                        live.parent.mkdir(parents=True, exist_ok=True)
                        restored.replace(live)
                    if components.get("user_database", False):
                        _check_sqlite(USER_DB_PATH)
                    if components.get("library_database", False):
                        _check_sqlite(DATA_DB_PATH)
                except Exception:
                    for live, previous in reversed(applied):
                        if live.exists():
                            if live.is_dir():
                                shutil.rmtree(live)
                            else:
                                live.unlink()
                        if previous is not None and previous.exists():
                            previous.replace(live)
                    raise

            if components[ATTACHMENTS_COMPONENT]:
                # Additive, create-only, and outside the atomic block: it reads the
                # now-restored user DB and can never corrupt the completed restore.
                _restore_attachments(staging / ATTACHMENTS_ARCHIVE_ROOT, USER_DB_PATH)

        return {
            "status": "restored",
            "name": source.name,
            "components": components,
            "rollback_path": str(rollback_dir),
            "restart_required": True,
            "message": "Metadata restored and verified. External images were not changed. Restart Danbooru before continuing.",
        }
    finally:
        _bundle_lock.release()
