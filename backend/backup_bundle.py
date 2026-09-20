"""Manual, user-directed metadata backup bundles and validated restoration."""
from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import tempfile
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
    RECOVERY_DIR,
    check_recovery_path,
    ARTIST_PROFILE_ARCHIVE_DIR,
    DATA_DB_PATH,
    METADATA_DIR,
    SIDECAR_DIR,
    USER_DB_PATH,
    get_backup_config,
    runtime_config_snapshot,
    save_config,
    validate_backup_destination,
)


logger = logging.getLogger("keivotos.backups")
BACKUP_FORMAT_VERSION = 1
BACKUP_FORMAT = "danbooru-metadata-backup"
BACKUP_SUFFIX = ".keivotosbk"
LEGACY_BACKUP_SUFFIXES = (".whbackup",)
SUPPORTED_BACKUP_SUFFIXES = (BACKUP_SUFFIX, *LEGACY_BACKUP_SUFFIXES)


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
# Resolved source paths, also used by isolated storage fixtures.
COMPONENTS = {
    key: (component.archive_name, component.source)
    for key, component in BACKUP_COMPONENTS.items() if component.kind != "attachments"
}
# Files-base attachment bytes live inside the user's own folder (outside the
# metadata tree), keyed by content hash. They are handled specially: bundled by
# hash on backup and re-materialized additively after metadata replacement.
# Existing bytes always win; attachment failures are reported independently.
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
    if not re.fullmatch(r"[a-f0-9]{32}", content_hash) or (ext and not re.fullmatch(r"[a-z0-9_-]+", ext)):
        raise ValueError("Invalid attachment hash or extension")
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
        source = attachment_store.resolve_attachment(row["stored_root"], row["content_hash"], ext)
        if source.is_file():
            records[arcname] = source
    return records


def _restore_attachments(bundle_dir: Path, user_db_path: Path) -> dict[str, int]:
    """Re-materialize bundled attachment bytes to their recorded store location.

    Additive and create-only: it never overwrites an existing file and never
    deletes anything, so it cannot corrupt the just-completed restore. Each file
    is attempted independently; a missing target drive skips only that file.
    """
    result = {"restored": 0, "existing": 0, "missing": 0, "failed": 0}
    path = Path(user_db_path)
    if not path.exists():
        return result
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        try:
            rows = connection.execute(
                "SELECT content_hash, file_name, media_type, stored_root "
                "FROM files_annotation_attachments WHERE stored_root IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            return result
    finally:
        connection.close()
    for row in rows:
        try:
            ext = attachment_store.extension_for(row["file_name"], row["media_type"])
            bundled = bundle_dir / _attachment_arcname(row["content_hash"], ext)
            target = attachment_store.resolve_attachment(row["stored_root"], row["content_hash"], ext)
            check_recovery_path(target)
            if target.exists():
                result["existing"] += 1
                continue
            if not bundled.is_file():
                result["missing"] += 1
                continue
            with bundled.open("rb") as stream:
                if hashlib.file_digest(stream, "md5").hexdigest() != row["content_hash"]:
                    raise ValueError("Attachment bytes do not match their hash")
            target.parent.mkdir(parents=True, exist_ok=True)
            # Publish a complete file exclusively; a concurrent writer wins.
            with tempfile.TemporaryDirectory(prefix=".keivotos-attachment-", dir=target.parent) as temporary:
                candidate = Path(temporary) / "attachment"
                shutil.copy2(bundled, candidate)
                try:
                    _publish_attachment(candidate, target)
                except FileExistsError:
                    result["existing"] += 1
                else:
                    result["restored"] += 1
        except (OSError, ValueError, RuntimeError):
            result["failed"] += 1
    return result


def _publish_attachment(candidate: Path, target: Path) -> None:
    try:
        os.link(candidate, target)
    except OSError as error:
        if error.errno not in {errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EXDEV}:
            raise
        # FAT/exFAT stores do not support hard links. Exclusive creation still
        # guarantees that an existing attachment can never be overwritten.
        with target.open("xb") as destination:
            try:
                with candidate.open("rb") as source:
                    shutil.copyfileobj(source, destination)
                destination.flush()
            except Exception:
                destination.close()
                target.unlink(missing_ok=True)
                raise


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
    from automatic_backups import automatic_backup_status
    return {
        "options": config.get("options", {}),
        "default_destination": config.get("default_destination", str(destination)),
        "automatic_status": automatic_backup_status(),
        "destination": str(destination),
        "components": normalized_components(config["components"]),
        "estimate": backup_estimate(config["components"]),
        "backups": list_backups(destination),
    }


def update_backup_configuration(components: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = normalized_components(components)
    if not any(selected.values()):
        raise ValueError("Select at least one backup component")
    updates = {"backup_components": {**get_backup_config()["components"], **selected}}
    if options is not None:
        options = dict(options)
        if options["location"] == "custom":
            options["custom_location"] = str(validate_backup_destination(options["custom_location"]))
        updates["backup_options"] = options
    save_config(updates)
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


def create_backup_bundle(components: dict[str, Any] | None = None, *, automatic_id: str | None = None) -> dict[str, Any]:
    if not _bundle_lock.acquire(blocking=False):
        raise RuntimeError("A backup or restore is already running")
    try:
        if automatic_id is not None and not re.fullmatch(r"[a-f0-9]{32}", automatic_id):
            raise ValueError("Invalid automatic backup identity")
        requested = normalized_components(components)
        selected = dict(requested)
        omitted = []
        for key, (_archive_name, source) in COMPONENTS.items():
            if selected[key] and BACKUP_COMPONENTS[key].owner != "suite" and not source.exists():
                selected[key] = False
                omitted.append(key)
        if not any(selected.values()):
            raise ValueError("Select at least one backup component")
        destination = validate_backup_destination(get_backup_config()["destination"])
        destination.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time())
        prefix = f"automatic_{automatic_id}" if automatic_id else f"backup_{stamp}"
        final_path = destination / f"{prefix}{BACKUP_SUFFIX}"
        counter = 2
        while os.path.lexists(final_path) or os.path.lexists(final_path.with_name(final_path.name + ".partial")):
            final_path = destination / f"{prefix}_{counter}{BACKUP_SUFFIX}"
            counter += 1
        partial_path = final_path.with_name(final_path.name + ".partial")

        # Stage beside the requested backup destination. The metadata source
        # only needs to be readable, and the staging files stay on the same
        # writable volume as the final bundle.
        logger.info("Starting %s backup", "automatic" if automatic_id else "manual")
        with tempfile.TemporaryDirectory(prefix=".keivotos-backup-", dir=destination) as temporary_name:
            temporary = Path(temporary_name)
            staged: dict[str, Path] = {}
            with exclusive_database_access():
                for key, (_archive_name, source) in COMPONENTS.items():
                    if selected[key] and BACKUP_COMPONENTS[key].kind == "sqlite":
                        snapshot = temporary / f"{key}.sqlite"
                        _sqlite_snapshot(source, snapshot)
                        staged[key] = snapshot
                if selected[ATTACHMENTS_COMPONENT] and "user_database" not in staged:
                    snapshot = temporary / "attachment-user.sqlite"
                    _sqlite_snapshot(USER_DB_PATH, snapshot)
                    staged["attachment_user"] = snapshot

            manifest: dict[str, Any] = {
                "automatic_id": automatic_id,
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
            with zipfile.ZipFile(partial_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
                for key, (archive_name, source) in COMPONENTS.items():
                    if not selected[key]:
                        continue
                    actual_source = staged.get(key, source)
                    _write_tree(archive, actual_source, archive_name)
                if selected[ATTACHMENTS_COMPONENT]:
                    for arcname, source in _attachment_records(staged.get("user_database", staged.get("attachment_user"))).items():
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

        logger.info("Backup verified: %s; omitted components: %s", final_path.name, ", ".join(omitted) or "none")
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
    seen = set()
    for info in archive.infolist():
        # ZipInfo normalizes Windows separators and truncates NULs while reading.
        # Reject altered names before trusting the normalized extraction path.
        if info.orig_filename != info.filename:
            raise ValueError(f"Unsafe backup entry: {info.orig_filename!r}")
        name = info.filename.rstrip("/")
        path = PurePosixPath(name)
        mode = info.external_attr >> 16
        if (not path.parts or path.is_absolute() or ".." in path.parts
                or "\\" in name or ":" in name or path.as_posix() != name
                or name.casefold() in seen or stat.S_ISLNK(mode)):
            raise ValueError(f"Unsafe backup entry: {info.filename}")
        seen.add(name.casefold())
        members.append(info)
    return members


def _quiesce_sqlite(path: Path) -> None:
    """Refuse replacement if an external connection prevents a full checkpoint."""
    if not path.exists():
        return
    connection = sqlite3.connect(path, timeout=1)
    try:
        row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if row and row[0]:
            raise RuntimeError(f"Database is busy: {path.name}")
    finally:
        connection.close()


def _copy_verified(source: Path, destination: Path) -> None:
    """Keep rollback evidence on the suite volume; verify before replacing live data."""
    check_recovery_path(source)
    if source.is_dir():
        for item in source.rglob("*"):
            check_recovery_path(item)
        shutil.copytree(source, destination)
        for item in source.rglob("*"):
            if item.is_file():
                _verify_copy(item, destination / item.relative_to(source))
    else:
        shutil.copy2(source, destination)
        _verify_copy(source, destination)


def _verify_copy(source: Path, destination: Path) -> None:
    with source.open("rb") as left, destination.open("rb") as right:
        if hashlib.file_digest(left, "sha256").digest() != hashlib.file_digest(right, "sha256").digest():
            raise RuntimeError(f"Restore copy verification failed: {source.name}")


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
        unsupported = {key for key, included in declared.items() if included and key not in _component_keys()}
        if unsupported:
            raise ValueError("Backup component restore support is unavailable: " + ", ".join(sorted(unsupported)))
        # Restore is determined by the archive, never by today's saved preferences.
        if any(not isinstance(value, bool) for value in declared.values()):
            raise ValueError("Backup component selections must be booleans")
        components = {key: declared.get(key, False) for key in _component_keys()}
        check_recovery_path(RECOVERY_DIR)
        RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
        rollback_dir = Path(tempfile.mkdtemp(prefix="restore_", dir=RECOVERY_DIR))
        attachment_result = {"restored": 0, "existing": 0, "missing": 0, "failed": 0}

        with tempfile.TemporaryDirectory(prefix=".restore-staging-", dir=RECOVERY_DIR) as temporary:
            staging = Path(temporary)
            with zipfile.ZipFile(source, "r") as archive:
                archive.extractall(staging, members=_safe_members(archive))
            replacements = []
            for key, (archive_name, live) in COMPONENTS.items():
                if not components[key]:
                    continue
                restored = staging / archive_name
                if BACKUP_COMPONENTS[key].kind == "sqlite":
                    _check_sqlite(restored)
                elif not restored.exists():
                    # Legacy ZIPs do not record empty directory entries.
                    continue
                elif not restored.is_dir():
                    raise ValueError(f"Expected a directory for {key}")
                check_recovery_path(live)
                replacements.append((key, live, restored))

            with exclusive_database_access():
                # Local preparations make the install/rollback renames atomic even
                # when a module lives on a different volume from suite recovery.
                prepared = []
                applied = []
                try:
                    for key, live, restored in replacements:
                        if BACKUP_COMPONENTS[key].kind == "sqlite":
                            _quiesce_sqlite(live)
                        live.parent.mkdir(parents=True, exist_ok=True)
                        local = Path(tempfile.mkdtemp(prefix=".keivotos-restore-", dir=live.parent))
                        prepared.append(local)
                        _copy_verified(restored, local / "incoming")
                        if live.exists():
                            _copy_verified(live, rollback_dir / key)
                        # Journals are moved with their database and restored on failure.
                        paths = [live]
                        if BACKUP_COMPONENTS[key].kind == "sqlite":
                            paths += [Path(str(live) + suffix) for suffix in ("-wal", "-shm")]
                        for index, path in enumerate(paths):
                            previous = local / f"previous-{index}" if path.exists() else None
                            if previous is not None:
                                path.replace(previous)
                            applied.append((path, previous, local / f"rejected-{index}"))
                        (local / "incoming").replace(live)
                    for key, live, _ in replacements:
                        if BACKUP_COMPONENTS[key].kind == "sqlite":
                            _check_sqlite(live)
                except Exception as error:
                    failures = []
                    for live, previous, rejected in reversed(applied):
                        try:
                            if live.exists():
                                live.replace(rejected)
                            if previous is not None:
                                previous.replace(live)
                        except OSError as rollback_error:
                            failures.append(str(rollback_error))
                    if failures:
                        # Never clean up local originals after a failed rollback.
                        raise RuntimeError(f"Restore rollback needs recovery from {rollback_dir}; local copies: {prepared}") from error
                    for local in prepared:
                        shutil.rmtree(local)
                    raise
                else:
                    for local in prepared:
                        shutil.rmtree(local)
                if components[ATTACHMENTS_COMPONENT]:
                    attachment_result = _restore_attachments(staging / ATTACHMENTS_ARCHIVE_ROOT, USER_DB_PATH)

        return {
            "status": "restored",
            "name": source.name,
            "components": components,
            "rollback_path": str(rollback_dir),
            "restart_required": True,
            "attachments": attachment_result,
            "message": "Metadata restored and verified. External images were not changed. Restart Keivotos before continuing."
            + (f" Attachment recovery incomplete: {attachment_result['missing']} missing, {attachment_result['failed']} failed."
               if attachment_result["missing"] or attachment_result["failed"] else ""),
        }
    finally:
        _bundle_lock.release()
