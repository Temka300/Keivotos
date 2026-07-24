"""Central configuration and the external Keivotos writable-data layout."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
from ctypes import wintypes
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from module_registry import ModuleRegistry, build_registry
from product import SUITE_NAME, VERSION


def _resource_root() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled).resolve() if bundled else Path(__file__).resolve().parent.parent


CODE_ROOT = _resource_root()
SOURCE_CONFIG_FILE = CODE_ROOT / "config.json"


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value: str) -> "_Guid":
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


FOLDERID_LOCAL_APP_DATA = _Guid.parse("F1B32785-6FBA-4FCF-9D55-7B8E7F157091")


def _windows_known_folder(folder_id: _Guid) -> Path | None:
    if os.name != "nt":
        return None
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.OleDLL("ole32")
    except (AttributeError, OSError):
        return None
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_Guid),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None
    raw_path = ctypes.c_void_p()
    result = shell32.SHGetKnownFolderPath(
        ctypes.byref(folder_id),
        0,
        None,
        ctypes.byref(raw_path),
    )
    if result != 0 or not raw_path.value:
        return None
    try:
        return Path(ctypes.wstring_at(raw_path.value))
    finally:
        ole32.CoTaskMemFree(raw_path)


def windows_local_app_data_directory() -> Path | None:
    """Return the machine-local Windows application-data known folder."""
    return _windows_known_folder(FOLDERID_LOCAL_APP_DATA)


def local_app_data_directory() -> Path:
    windows_path = windows_local_app_data_directory()
    if windows_path is not None:
        return windows_path
    configured = os.environ.get("XDG_DATA_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".local" / "share"


def _executable_directory() -> Path:
    """Directory that holds the running program.

    For a frozen (PyInstaller) build this is the folder next to Keivotos.exe;
    from source it is the repository root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


PORTABLE_MARKER_NAME = "portable.txt"


def _portable_suite_home() -> Path | None:
    """Return a portable data home when a ``portable.txt`` marker sits next to
    the program, otherwise ``None``.

    An empty marker means ``<program folder>/data``; a marker that contains a
    path uses that path instead. Deleting the marker restores the per-user
    application-data default without touching any data left behind.
    """
    marker = _executable_directory() / PORTABLE_MARKER_NAME
    if not marker.is_file():
        return None
    try:
        configured = marker.read_text(encoding="utf-8").strip()
    except OSError:
        configured = ""
    return Path(configured).expanduser() if configured else _executable_directory() / "data"


# Writable-data home precedence, highest first:
#   1. KEIVOTOS_HOME environment variable (explicit override; used by launchers)
#   2. a portable.txt marker beside the program -> <program folder>/data
#   3. the per-user application-data default (%LOCALAPPDATA%\Keivotos)
DEFAULT_SUITE_HOME = local_app_data_directory() / "Keivotos"
_explicit_suite_home = os.environ.get("KEIVOTOS_HOME", "").strip()
_portable_suite_home_path = None if _explicit_suite_home else _portable_suite_home()
if _explicit_suite_home:
    SUITE_HOME = Path(_explicit_suite_home).expanduser()
    _home_is_external = True
elif _portable_suite_home_path is not None:
    SUITE_HOME = _portable_suite_home_path
    _home_is_external = True
else:
    SUITE_HOME = DEFAULT_SUITE_HOME
    _home_is_external = False
MODULES_DIR = SUITE_HOME / "modules"
_DEFAULT_MODULE_REGISTRY = build_registry(SUITE_HOME, VERSION)
_DEFAULT_FILES_MODULE = _DEFAULT_MODULE_REGISTRY.require("files")
# Danbooru is optional: its package can be removed from the registry. Nothing at
# suite level may require it, so the descriptor is looked up leniently. The
# compatibility paths below keep their conventional locations when it is absent,
# where they are simply unused.
DANBOORU_SLUG = "danbooru"
_DEFAULT_DANBOORU_MODULE = _DEFAULT_MODULE_REGISTRY.get(DANBOORU_SLUG)
MODULE_HOME = (
    _DEFAULT_DANBOORU_MODULE.home
    if _DEFAULT_DANBOORU_MODULE is not None
    else MODULES_DIR / DANBOORU_SLUG
)
DEFAULT_LIBRARY_DIR = MODULE_HOME / "library"
DEFAULT_METADATA_DIR = MODULE_HOME
LEGACY_DEFAULT_METADATA_DIR = MODULE_HOME / "metadata"
DEFAULT_GALLERY_DL_DIR = MODULE_HOME / "gallery-dl"
DEFAULT_BACKUP_DIR = SUITE_HOME / "backups"
LEGACY_MODULE_BACKUP_DIR = DEFAULT_BACKUP_DIR / DANBOORU_SLUG
LOG_DIR = SUITE_HOME / "logs"
LOG_FILE_LIMIT_MB = 5
LOG_ROLLOVER_FILES = 5
LOG_RETENTION_FILES = 30
LOG_SESSION_ID = f"{datetime.now().astimezone():%Y-%m-%d_%H-%M-%S}-p{os.getpid()}"
SUITE_LOG_PREFIX = SUITE_NAME.casefold()
RUNTIME_LOG_FILE = LOG_DIR / f"{SUITE_LOG_PREFIX}-runtime-{LOG_SESSION_ID}.log"
ACCESS_LOG_FILE = LOG_DIR / f"{SUITE_LOG_PREFIX}-access-{LOG_SESSION_ID}.log"
RUNTIME_CONFIG_FILE = SUITE_HOME / "config.json"

# Compatibility name used by existing APIs; it means the module's writable
# root inside the Keivotos application-data layout.
DOCUMENTS_ROOT = DEFAULT_METADATA_DIR

_defaults: dict[str, Any] = {
    "data_root": str(DEFAULT_LIBRARY_DIR),
    "metadata_dir": str(DEFAULT_METADATA_DIR),
    "gallery_dl_dir": str(DEFAULT_GALLERY_DL_DIR),
    "automation_enabled": False,
    "automation_enabled_at": None,
    "automation_interval_minutes": 15,
    "backup_components": {
        "user_database": True,
        "library_database": True,
        "sidecars": True,
        "sidecar_history": False,
        "artist_profile_archive": False,
        "file_attachments": True,
    },
    "thumbnail_cache_limit_gb": 10,
}
_external_path_defaults = {
    key: _defaults[key]
    for key in ("data_root", "metadata_dir", "gallery_dl_dir")
}


class ConfigurationError(RuntimeError):
    """A user-editable configuration file could not be loaded safely."""


def _record_configuration_error(message: str) -> None:
    """Persist import-time failures before normal logging is available."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        with RUNTIME_LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} ERROR config: Configuration error: {message}\n")
    except OSError:
        pass


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        message = f"Could not read configuration file {path}: {exc}"
        _record_configuration_error(message)
        raise ConfigurationError(message) from exc
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        message = (
            f"Invalid JSON in {path} at line {exc.lineno}, column {exc.colno}: {exc.msg}. "
            "Fix or rename this file, then start Keivotos again."
        )
        _record_configuration_error(message)
        raise ConfigurationError(message) from exc
    if not isinstance(value, dict):
        message = f"Configuration must contain a JSON object: {path}"
        _record_configuration_error(message)
        raise ConfigurationError(message)
    return value


def _files_match(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False

    def digest(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    return digest(left) == digest(right)


def _copy_verified_tree(source: Path, destination: Path) -> tuple[int, int]:
    """Resume a copy without overwriting conflicts, verifying every file."""
    if source.is_symlink():
        raise RuntimeError(f"Refused to migrate symbolic link: {source}")
    if source.is_dir():
        if destination.exists() and not destination.is_dir():
            raise RuntimeError(f"Migration destination conflicts with a directory: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        copied = copied_bytes = 0
        for child in sorted(source.iterdir(), key=lambda item: item.name.casefold()):
            child_count, child_bytes = _copy_verified_tree(child, destination / child.name)
            copied += child_count
            copied_bytes += child_bytes
        return copied, copied_bytes
    if not source.is_file():
        raise RuntimeError(f"Refused unsupported migration entry: {source}")
    if destination.exists():
        if not destination.is_file() or not _files_match(source, destination):
            raise RuntimeError(
                "Application-data migration found a conflicting destination. "
                f"Preserved both locations for manual review: {source} and {destination}"
            )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    if not _files_match(source, destination):
        raise RuntimeError(f"Application-data migration verification failed: {source}")
    return 1, source.stat().st_size


def _rebase_migrated_config(config_path: Path, source_home: Path, destination_home: Path) -> bool:
    """Retarget only copied paths that previously lived below a migrated root."""
    if not config_path.is_file():
        return False
    config = _read_json(config_path)
    changed = False
    for key in ("data_root", "metadata_dir", "gallery_dl_dir"):
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            continue
        try:
            relative = path.resolve(strict=False).relative_to(source_home)
        except ValueError:
            continue
        config[key] = str(destination_home / relative)
        changed = True
    if not changed:
        return False
    temporary = config_path.with_suffix(".json.migration.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temporary.replace(config_path)
    return True


def _verify_module_databases(module_home: Path) -> None:
    for database_name in ("user.sqlite", "danbooru.sqlite"):
        path = module_home / database_name
        if not path.is_file():
            continue
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            row = connection.execute("PRAGMA quick_check").fetchone()
        finally:
            connection.close()
        if not row or row[0] != "ok":
            raise RuntimeError(f"Application-data migration SQLite check failed for {database_name}: {row!r}")


def _configured_previous_module_homes() -> list[Path]:
    modules = MODULES_DIR.resolve(strict=False)
    candidates: dict[str, Path] = {}
    for key in ("data_root", "metadata_dir", "gallery_dl_dir"):
        value = _read_json(RUNTIME_CONFIG_FILE).get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        path = Path(value).expanduser()
        if not path.is_absolute():
            continue
        resolved = path.resolve(strict=False)
        try:
            relative = resolved.relative_to(modules)
        except ValueError:
            continue
        if not relative.parts:
            continue
        candidate = modules / relative.parts[0]
        if candidate != MODULE_HOME.resolve(strict=False) and candidate.is_dir():
            candidates[str(candidate).casefold()] = candidate
    return list(candidates.values())


def _discover_previous_module_home() -> tuple[Path | None, str]:
    configured = _configured_previous_module_homes()
    if len(configured) > 1:
        raise RuntimeError("Module migration found conflicting configured module roots")
    if configured:
        return configured[0], "configured"
    if MODULE_HOME.exists() or not MODULES_DIR.is_dir():
        return None, "destination-exists" if MODULE_HOME.exists() else "source-missing"

    markers = {"user.sqlite", "danbooru.sqlite", "metadata", "sidecars", "library", "gallery-dl"}
    candidates = [
        path
        for path in MODULES_DIR.iterdir()
        if path.is_dir()
        and not path.is_symlink()
        and path.name != _DEFAULT_DANBOORU_MODULE.slug
        and any((path / marker).exists() for marker in markers)
    ]
    if len(candidates) > 1:
        raise RuntimeError("Module migration found multiple prior data roots; configure metadata_dir explicitly")
    return (candidates[0], "discovered") if candidates else (None, "source-missing")


def migrate_previous_module_home(
    source: Path | None = None,
    destination: Path | None = None,
) -> dict[str, Any]:
    """Copy and verify a prior module layout without removing its source data."""
    reason = "explicit"
    if source is None:
        source, reason = _discover_previous_module_home()
    if source is None:
        return {"migrated": False, "reason": reason, "files": 0, "bytes": 0}

    source_home = source.expanduser().resolve(strict=False)
    destination_home = (destination or MODULE_HOME).expanduser().resolve(strict=False)
    if not source_home.is_dir():
        return {"migrated": False, "reason": "source-missing", "files": 0, "bytes": 0}
    if source_home.is_symlink():
        raise RuntimeError(f"Refused symbolic-link module migration: {source_home}")
    if source_home == destination_home or source_home in destination_home.parents or destination_home in source_home.parents:
        raise RuntimeError("Module migration source and destination must be separate directories")
    if destination_home.exists() and (destination_home.is_symlink() or not destination_home.is_dir()):
        raise RuntimeError(f"Module migration destination is unsafe: {destination_home}")

    staging = destination_home.with_name(destination_home.name + ".migration-staging")
    copy_target = destination_home
    if not destination_home.exists():
        if staging.exists() and (staging.is_symlink() or not staging.is_dir()):
            raise RuntimeError(f"Module migration staging is unsafe: {staging}")
        destination_home.parent.mkdir(parents=True, exist_ok=True)
        staging.mkdir(parents=True, exist_ok=True)
        copy_target = staging

    files = copied_bytes = 0
    for child in sorted(source_home.iterdir(), key=lambda item: item.name.casefold()):
        child_files, child_bytes = _copy_verified_tree(child, copy_target / child.name)
        files += child_files
        copied_bytes += child_bytes
    _verify_module_databases(copy_target)
    if copy_target == staging:
        staging.replace(destination_home)

    source_backup = SUITE_HOME / "backups" / source_home.name
    if source_backup.is_dir() and not source_backup.is_symlink():
        backup_files, backup_bytes = _copy_verified_tree(source_backup, DEFAULT_BACKUP_DIR)
        files += backup_files
        copied_bytes += backup_bytes
    config_rebased = _rebase_migrated_config(RUNTIME_CONFIG_FILE, source_home, destination_home)
    return {
        "migrated": True,
        "reason": reason,
        "files": files,
        "bytes": copied_bytes,
        "config_rebased": config_rebased,
        "source": str(source_home),
        "destination": str(destination_home),
    }


def promote_user_database(
    legacy: Path | None = None,
    destination: Path | None = None,
) -> dict[str, Any]:
    """Promote the shared user database to the suite root once (verified copy).

    ``user.sqlite`` is the one irreplaceable file and must live at suite level so
    it exists even with no module enabled. This copies a legacy
    ``modules/<module>/user.sqlite`` up to ``SUITE_HOME/user.sqlite``, verifies
    the copy (size + ``PRAGMA quick_check``), atomically installs it, and leaves
    the legacy source untouched. Idempotent (skips once the suite-level file
    exists) and fail-closed. See docs/important/SUITE_MODULE_CONTRACT.md 3.1.
    """
    destination_db = (destination or (SUITE_HOME / "user.sqlite")).expanduser().resolve(strict=False)
    legacy_db = (legacy or (MODULE_HOME / "user.sqlite")).expanduser().resolve(strict=False)
    if destination_db.exists():
        return {"promoted": False, "reason": "already-suite-level"}
    if legacy_db == destination_db:
        return {"promoted": False, "reason": "same-path"}
    if not legacy_db.is_file():
        return {"promoted": False, "reason": "no-legacy"}
    if legacy_db.is_symlink():
        raise RuntimeError(f"Refused symbolic-link user database promotion: {legacy_db}")

    # Fold any write-ahead log back into the main file so a single-file copy is
    # complete before we duplicate it.
    checkpoint_connection = sqlite3.connect(legacy_db)
    try:
        checkpoint_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        checkpoint_connection.close()

    destination_db.parent.mkdir(parents=True, exist_ok=True)
    staging = destination_db.with_name(destination_db.name + ".promoting")
    if staging.exists() and (staging.is_symlink() or not staging.is_file()):
        raise RuntimeError(f"User database promotion staging is unsafe: {staging}")
    if staging.exists():
        staging.unlink()
    shutil.copy2(legacy_db, staging)
    try:
        if not _files_match(legacy_db, staging):
            raise RuntimeError(f"User database promotion verification failed: {legacy_db}")
        verify_connection = sqlite3.connect(f"file:{staging.as_posix()}?mode=ro", uri=True)
        try:
            row = verify_connection.execute("PRAGMA quick_check").fetchone()
        finally:
            verify_connection.close()
        if not row or row[0] != "ok":
            raise RuntimeError(f"User database promotion SQLite check failed: {row!r}")
    except Exception:
        staging.unlink(missing_ok=True)
        raise
    staging.replace(destination_db)  # atomic install; legacy source is preserved
    return {
        "promoted": True,
        "reason": "copied-and-verified",
        "source": str(legacy_db),
        "destination": str(destination_db),
    }


def promote_legacy_module_backups(
    source: Path | None = None,
    destination: Path | None = None,
) -> dict[str, Any]:
    """Copy old module-scoped backups into the suite backup directory.

    The legacy directory is deliberately preserved. Existing identical files
    are verified and conflicts fail closed rather than being overwritten.
    """
    source_dir = (source or LEGACY_MODULE_BACKUP_DIR).expanduser().resolve(strict=False)
    destination_dir = (destination or DEFAULT_BACKUP_DIR).expanduser().resolve(strict=False)
    if not source_dir.is_dir():
        return {"promoted": False, "reason": "source-missing", "files": 0, "bytes": 0}
    if source_dir.is_symlink():
        raise RuntimeError(f"Refused symbolic-link backup migration: {source_dir}")
    if source_dir == destination_dir:
        return {"promoted": False, "reason": "same-path", "files": 0, "bytes": 0}
    destination_dir.mkdir(parents=True, exist_ok=True)
    files = copied_bytes = 0
    for child in sorted(source_dir.iterdir(), key=lambda item: item.name.casefold()):
        child_files, child_bytes = _copy_verified_tree(child, destination_dir / child.name)
        files += child_files
        copied_bytes += child_bytes
    return {
        "promoted": files > 0,
        "reason": "copied-and-verified" if files else "empty-source",
        "files": files,
        "bytes": copied_bytes,
        "source": str(source_dir),
        "destination": str(destination_dir),
    }


_migration_requested = os.environ.pop("KEIVOTOS_MIGRATE_LEGACY_HOME", "") == "1"
MODULE_HOME_MIGRATION = (
    migrate_previous_module_home()
    if _migration_requested
    else {"migrated": False, "reason": "not-requested", "files": 0, "bytes": 0}
)


def _load() -> dict[str, Any]:
    config = {**_defaults, **_read_json(SOURCE_CONFIG_FILE)}
    # An external home (KEIVOTOS_HOME or a portable.txt marker) ignores the
    # checked-in template paths and anchors every writable default under it.
    if _home_is_external:
        config.update(_external_path_defaults)
    config.update(_read_json(RUNTIME_CONFIG_FILE))
    config.pop("backup_destination", None)
    return config


_cfg = _load()


def _resolve_path(value: str, base: Path = MODULE_HOME) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


DATA_ROOT = _resolve_path(str(_cfg["data_root"]))
METADATA_DIR = _resolve_path(str(_cfg["metadata_dir"]))
if METADATA_DIR.resolve(strict=False) == LEGACY_DEFAULT_METADATA_DIR.resolve(strict=False):
    METADATA_DIR = DEFAULT_METADATA_DIR
    _cfg["metadata_dir"] = str(DEFAULT_METADATA_DIR)
GALLERY_DL_DIR = _resolve_path(str(_cfg.get("gallery_dl_dir", DEFAULT_GALLERY_DL_DIR)))

DATA_DB_PATH = METADATA_DIR / "danbooru.sqlite"
# The shared, irreplaceable user DB lives at suite level (not under a module),
# so it exists with zero modules enabled. A legacy module-home copy is promoted
# here on startup via promote_user_database(). See SUITE_MODULE_CONTRACT.md 3.1.
USER_DB_PATH = SUITE_HOME / "user.sqlite"
THUMB_DIR = METADATA_DIR / "thumbnails"
SIDECAR_DIR = METADATA_DIR / "sidecars"
ARTIST_PROFILE_ARCHIVE_DIR = METADATA_DIR / "artist_profile_archive"
CREDENTIALS_PATH = METADATA_DIR / "danbooru_credentials.json"

# --- Files base (V1.1.0) ---
# The always-on neutral file layer. Its index is disposable (rebuildable from
# disk) and lives at suite level, NOT under modules/, because the base exists
# even with zero modules enabled. See docs/important/SUITE_MODULE_CONTRACT.md.
BASE_HOME = _DEFAULT_FILES_MODULE.home
FILES_DB_PATH = _DEFAULT_FILES_MODULE.database
FILES_THUMB_DIR = BASE_HOME / "thumbnails"

# Effective descriptors are the registry consumed by the suite shell. Danbooru
# still supports an explicitly configured metadata directory, so its module DB
# and credential paths are rebound while its stable module home remains fixed.
FILES_MODULE = replace(_DEFAULT_FILES_MODULE, home=BASE_HOME, database=FILES_DB_PATH)
MODULE_REGISTRY: ModuleRegistry = _DEFAULT_MODULE_REGISTRY.replacing(FILES_MODULE)
DANBOORU_MODULE = None
if _DEFAULT_DANBOORU_MODULE is not None:
    DANBOORU_MODULE = replace(
        _DEFAULT_DANBOORU_MODULE,
        database=DATA_DB_PATH,
        credentials=CREDENTIALS_PATH,
    )
    MODULE_REGISTRY = MODULE_REGISTRY.replacing(DANBOORU_MODULE)


def _merge_legacy_entry(source: Path, destination: Path) -> tuple[int, int]:
    """Move one legacy entry without overwriting a different destination."""
    if source.is_symlink():
        raise RuntimeError(f"Refused to migrate symbolic link: {source}")
    if not destination.exists():
        source.replace(destination)
        return (1, 0)
    if source.is_dir() and destination.is_dir():
        moved = deduplicated = 0
        for child in sorted(source.iterdir(), key=lambda item: item.name.casefold()):
            child_moved, child_deduplicated = _merge_legacy_entry(child, destination / child.name)
            moved += child_moved
            deduplicated += child_deduplicated
        source.rmdir()
        return moved, deduplicated
    if source.is_file() and destination.is_file() and _files_match(source, destination):
        source.unlink()
        return (0, 1)
    raise RuntimeError(
        "Legacy metadata migration found a conflicting destination. "
        f"Preserved both paths for manual review: {source} and {destination}"
    )


def migrate_legacy_default_metadata() -> dict[str, Any]:
    """Flatten the former module/metadata wrapper at startup, once and safely."""
    target = DEFAULT_METADATA_DIR.resolve(strict=False)
    legacy = LEGACY_DEFAULT_METADATA_DIR
    if METADATA_DIR.resolve(strict=False) != target or not legacy.exists():
        return {"migrated": False, "moved": 0, "deduplicated": 0}
    if legacy.is_symlink() or legacy.parent.resolve(strict=False) != target:
        raise RuntimeError(f"Refused unsafe legacy metadata migration: {legacy}")

    moved = deduplicated = 0
    for child in sorted(legacy.iterdir(), key=lambda item: item.name.casefold()):
        child_moved, child_deduplicated = _merge_legacy_entry(child, DEFAULT_METADATA_DIR / child.name)
        moved += child_moved
        deduplicated += child_deduplicated
    legacy.rmdir()
    return {"migrated": True, "moved": moved, "deduplicated": deduplicated}

def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


SCAN_FOLDERS: list[str] = _string_list(_cfg.get("scan_folders"))


def save_config(overrides: dict[str, Any]) -> None:
    """Persist user overrides outside the source tree and packaged app."""
    current = _read_json(RUNTIME_CONFIG_FILE)
    current.pop("backup_destination", None)
    sanitized = dict(overrides)
    sanitized.pop("backup_destination", None)
    current.update(sanitized)
    RUNTIME_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = RUNTIME_CONFIG_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temporary.replace(RUNTIME_CONFIG_FILE)
    _cfg.pop("backup_destination", None)
    _cfg.update(sanitized)


def runtime_config_snapshot() -> dict[str, Any]:
    """Return the effective, non-secret settings suitable for a backup bundle."""
    private_paths = {"data_root", "metadata_dir", "gallery_dl_dir"}
    return {
        key: value
        for key, value in _cfg.items()
        if key not in private_paths
    }


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def get_automation_config() -> dict[str, Any]:
    return {
        "enabled": bool(_cfg.get("automation_enabled", False)),
        "enabled_at": _cfg.get("automation_enabled_at"),
        "interval_minutes": _bounded_int(_cfg.get("automation_interval_minutes"), 15, 5, 1440),
    }


def get_backup_config() -> dict[str, Any]:
    defaults = dict(_defaults["backup_components"])
    components = _cfg.get("backup_components")
    if isinstance(components, dict):
        defaults.update({key: bool(value) for key, value in components.items() if key in defaults})
    return {"destination": str(DEFAULT_BACKUP_DIR), "components": defaults}


def get_thumbnail_cache_limit_bytes() -> int:
    value = _bounded_int(_cfg.get("thumbnail_cache_limit_gb"), 10, 1, 100)
    return value * 1024 * 1024 * 1024


def public_storage_config() -> dict[str, Any]:
    resolved = METADATA_DIR.resolve(strict=False)
    expected = DEFAULT_METADATA_DIR.resolve(strict=False)
    return {
        "metadata_dir": str(METADATA_DIR),
        "documents_default": str(DEFAULT_METADATA_DIR),
        "suite_home": str(SUITE_HOME),
        "module_home": str(MODULE_HOME),
        "library_dir": str(DATA_ROOT),
        "config_file": str(RUNTIME_CONFIG_FILE),
        "gallery_dl_dir": str(GALLERY_DL_DIR),
        "log_dir": str(LOG_DIR),
        "runtime_log_file": str(RUNTIME_LOG_FILE),
        "access_log_file": str(ACCESS_LOG_FILE),
        "log_retention_files": LOG_RETENTION_FILES,
        "mode": "keivotos" if resolved == expected else "custom",
    }


def get_config_path() -> Path:
    return RUNTIME_CONFIG_FILE
