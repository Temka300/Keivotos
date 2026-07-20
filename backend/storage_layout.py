"""Stable root identities and canonical sidecar paths for external libraries."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class LibraryRoot:
    root_id: str
    name: str
    path: Path


def new_root_id() -> str:
    return f"root-{uuid.uuid4().hex[:16]}"


def deterministic_root_id(path: Path) -> str:
    normalized = os.path.normcase(str(path.expanduser().resolve(strict=False)))
    return f"root-{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def load_library_roots(user_db_path: Path) -> list[LibraryRoot]:
    if not user_db_path.exists():
        return []
    connection = sqlite3.connect(user_db_path)
    connection.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(registered_folders)")}
        if not columns:
            return []
        has_root_id = "root_id" in columns
        has_display_name = "display_name" in columns
        select_parts = ["name", "path"]
        if has_root_id:
            select_parts.append("root_id")
        if has_display_name:
            select_parts.append("display_name")
        select = f"SELECT {', '.join(select_parts)} FROM registered_folders"
        result: list[LibraryRoot] = []
        for row in connection.execute(select):
            if not row["path"]:
                continue
            path = Path(row["path"]).expanduser().resolve(strict=False)
            root_id = row["root_id"] if has_root_id else None
            display_name = row["display_name"] if has_display_name else row["name"]
            result.append(LibraryRoot(str(root_id or deterministic_root_id(path)), str(display_name or row["name"]), path))
        return result
    finally:
        connection.close()


def matching_root(media_path: Path, roots: Iterable[LibraryRoot]) -> tuple[LibraryRoot, Path] | None:
    resolved = media_path.expanduser().resolve(strict=False)
    matches: list[tuple[int, LibraryRoot, Path]] = []
    for root in roots:
        try:
            relative = resolved.relative_to(root.path.resolve(strict=False))
        except ValueError:
            continue
        matches.append((len(root.path.parts), root, relative))
    if not matches:
        return None
    _, root, relative = max(matches, key=lambda item: item[0])
    return root, relative


def identity_for_media(media_path: Path, data_root: Path, roots: Iterable[LibraryRoot]) -> tuple[str, Path]:
    match = matching_root(media_path, roots)
    if match:
        root, relative = match
        return root.root_id, relative
    resolved = media_path.expanduser().resolve(strict=False)
    try:
        return "portable-root", resolved.relative_to(data_root.resolve(strict=False))
    except ValueError:
        digest = hashlib.sha256(os.path.normcase(str(resolved)).encode("utf-8")).hexdigest()[:16]
        return f"unregistered-{digest}", Path(media_path.name)


def canonical_sidecar_path(
    media_path: Path,
    suffix: str,
    data_root: Path,
    sidecar_dir: Path,
    roots: Iterable[LibraryRoot],
) -> Path:
    root_id, relative = identity_for_media(media_path, data_root, roots)
    return sidecar_dir / "roots" / root_id / relative.parent / (media_path.name + suffix)


def legacy_hashed_sidecar_path(media_path: Path, suffix: str, sidecar_dir: Path) -> Path:
    resolved = media_path.expanduser().resolve(strict=False)
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:16]
    return sidecar_dir / "_outside_root" / digest / (media_path.name + suffix)


def legacy_mirrored_sidecar_path(media_path: Path, suffix: str, data_root: Path, sidecar_dir: Path) -> Path | None:
    try:
        relative = media_path.expanduser().resolve(strict=False).relative_to(data_root.resolve(strict=False))
    except ValueError:
        return None
    return sidecar_dir / relative.parent / (media_path.name + suffix)


def sidecar_candidates(
    media_path: Path,
    suffix: str,
    data_root: Path,
    sidecar_dir: Path,
    roots: Iterable[LibraryRoot],
) -> list[Path]:
    candidates = [
        canonical_sidecar_path(media_path, suffix, data_root, sidecar_dir, roots),
        legacy_hashed_sidecar_path(media_path, suffix, sidecar_dir),
    ]
    mirrored = legacy_mirrored_sidecar_path(media_path, suffix, data_root, sidecar_dir)
    if mirrored is not None:
        candidates.append(mirrored)
    candidates.append(media_path.with_name(media_path.name + suffix))
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(str(candidate.resolve(strict=False)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def root_sidecar_directory(root_id: str, sidecar_dir: Path) -> Path:
    """Return a root's canonical sidecar directory after containment validation."""
    base = (sidecar_dir / "roots").resolve(strict=False)
    target = (base / root_id).resolve(strict=False)
    if target == base or base not in target.parents:
        raise ValueError("Invalid library root identity")
    return target


def current_sidecar_files_for_root(
    root: LibraryRoot,
    media_paths: Iterable[Path],
    data_root: Path,
    sidecar_dir: Path,
    suffixes: Iterable[str] = (".danbooru.json", ".tags.txt"),
) -> list[Path]:
    """List current central sidecars for a root without including adjacent media files."""
    suffix_list = tuple(suffixes)
    sidecar_base = sidecar_dir.resolve(strict=False)
    found: dict[str, Path] = {}

    canonical_root = root_sidecar_directory(root.root_id, sidecar_dir)
    if canonical_root.is_dir():
        for path in canonical_root.rglob("*"):
            if path.is_file() and path.name.endswith(suffix_list):
                resolved = path.resolve(strict=False)
                if sidecar_base in resolved.parents:
                    found[os.path.normcase(str(resolved))] = path

    for media_path in media_paths:
        for suffix in suffix_list:
            # Canonical files are collected by walking the stable root above.
            # These two candidates cover preservation-era layouts for indexed
            # media without ever touching a sidecar beside the external image.
            candidates = [
                legacy_hashed_sidecar_path(media_path, suffix, sidecar_dir),
                legacy_mirrored_sidecar_path(media_path, suffix, data_root, sidecar_dir),
            ]
            for candidate in candidates:
                if candidate is None or not candidate.is_file():
                    continue
                resolved = candidate.resolve(strict=False)
                if resolved == sidecar_base or sidecar_base not in resolved.parents:
                    continue
                found[os.path.normcase(str(resolved))] = candidate

    return sorted(found.values(), key=lambda path: os.path.normcase(str(path)))


def migrate_existing_sidecars(
    media_paths: Iterable[Path],
    data_root: Path,
    sidecar_dir: Path,
    roots: Iterable[LibraryRoot],
    suffixes: Iterable[str] = (".danbooru.json", ".tags.txt"),
) -> dict[str, int]:
    """Copy and verify legacy sidecars into the root-based layout; never delete originals."""
    copied = skipped = failed = 0
    root_list = list(roots)
    for media_path in media_paths:
        for suffix in suffixes:
            target = canonical_sidecar_path(media_path, suffix, data_root, sidecar_dir, root_list)
            if target.exists():
                skipped += 1
                continue
            source = next((candidate for candidate in sidecar_candidates(media_path, suffix, data_root, sidecar_dir, root_list)[1:] if candidate.exists()), None)
            if source is None:
                skipped += 1
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(target.name + ".migrating")
                shutil.copy2(source, temporary)
                if temporary.stat().st_size != source.stat().st_size:
                    raise OSError("copied sidecar size did not match source")
                temporary.replace(target)
                copied += 1
            except OSError:
                failed += 1
                try:
                    temporary.unlink(missing_ok=True)
                except (OSError, UnboundLocalError):
                    pass
    return {"copied": copied, "skipped": skipped, "failed": failed}
