from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing, nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from schema import create_data_indexes, ensure_data_schema  # noqa: E402
from storage_layout import (  # noqa: E402
    LibraryRoot,
    canonical_sidecar_path,
    identity_for_media,
    legacy_hashed_sidecar_path,
    load_library_roots,
    matching_root,
    sidecar_candidates as layout_sidecar_candidates,
)

try:
    from PIL import Image as _PILImage
except ImportError:  # Pillow is optional; minimal indexing then skips dimensions.
    _PILImage = None


DANBOORU_ROOT = "https://danbooru.donmai.us"
MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".jfif",
    ".png",
    ".webp",
    ".webm",
    ".gif",
    ".mp4",
}
DEFAULT_SCAN_FOLDERS: tuple[str, ...] = ()
DEFAULT_EXTRA_INCLUDES = (
    "artist_commentary",
    "children",
    "notes",
    "parent",
    "uploader",
)
TAG_FIELDS = {
    "artist": "tag_string_artist",
    "character": "tag_string_character",
    "copyright": "tag_string_copyright",
    "general": "tag_string_general",
    "meta": "tag_string_meta",
}
WINDOWS_BAD_CHARS = r'<>:"/\|?*'
MD5_RE = re.compile(r"(?<![0-9a-fA-F])([0-9a-fA-F]{32})(?![0-9a-fA-F])")
POST_ID_RE = re.compile(r"^__(\d+)__")
_LIBRARY_ROOTS: list[LibraryRoot] = []


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_project_path(path: Path, base: Path | None = None) -> Path:
    if path.is_absolute():
        return path
    return (base or project_root()) / path


def safe_segment(value: str, max_len: int = 96) -> str:
    value = value.strip()
    for char in WINDOWS_BAD_CHARS:
        value = value.replace(char, "_")
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip(" ._")
    if not value:
        value = "untagged"
    return value[:max_len].rstrip(" ._") or "untagged"


def parse_includes(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_EXTRA_INCLUDES)
    return [part.strip() for part in raw.split(",") if part.strip()]


def ensure_gallery_dl_command() -> list[str]:
    if getattr(sys, "frozen", False):
        bundled_executable = Path(sys.executable).resolve().parent / "gallery-dl.exe"
        if bundled_executable.is_file():
            return [str(bundled_executable)]
        raise RuntimeError("Portable gallery-dl.exe is missing beside Keivotos.exe")
    executable = shutil.which("gallery-dl")
    if executable:
        return [executable]
    return [sys.executable, "-m", "gallery_dl"]


def build_gallery_dl_config(args: argparse.Namespace, tag_query: str) -> Path:
    root = args.root.resolve()
    destination = getattr(args, "destination", None)
    if destination:
        output_dir = destination.expanduser().resolve(strict=False)
        base_directory = output_dir
        directory: list[str] = []
    else:
        tag_folder = args.tag_folder or safe_segment(tag_query)
        base_directory = root
        directory = [args.folder, tag_folder]
    work_dir = resolve_project_path(args.gallery_dl_dir).resolve()
    config_dir = work_dir / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)

    postprocessors = [
        {
            "name": "metadata",
            "mode": "json",
            "event": ["after", "skip"],
            "extension-format": "{extension}.danbooru.json",
            "indent": 2,
            "sort": True,
            "private": False,
        },
        {
            "name": "metadata",
            "mode": "print",
            "event": ["after", "skip"],
            "format": "GALLERY_PROGRESS:{id}",
        },
        {
            "name": "metadata",
            "mode": "tags",
            "event": ["after", "skip"],
            "extension-format": "{extension}.tags.txt",
        },
    ]

    danbooru_config: dict[str, Any] = {
        "directory": directory,
        "filename": args.filename,
        "metadata": parse_includes(args.metadata_includes),
        "ugoira": args.ugoira_zip,
        "external": args.external,
    }

    username = args.username or os.environ.get("DANBOORU_USERNAME")
    api_key = args.api_key or os.environ.get("DANBOORU_API_KEY")
    if username and api_key:
        danbooru_config["username"] = username
        danbooru_config["password"] = api_key

    config = {
        "extractor": {
            "base-directory": str(base_directory),
            "archive": str(args.archive or (work_dir / "danbooru.sqlite3")),
            "skip": True,
            "sleep-request": args.sleep_request,
            "sleep-429": args.sleep_429,
            "retries": args.retries,
            "path-restrict": "windows",
            "postprocessors": postprocessors,
            "danbooru": danbooru_config,
        }
    }

    # This file may contain an API key. Give every run a private transient
    # config rather than leaving credentials in a reusable work-file.
    config_path = config_dir / f"danbooru_{os.getpid()}_{time.time_ns()}.json"
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    try:
        config_path.chmod(0o600)
    except OSError:
        pass
    return config_path


def danbooru_posts_url(tag_query: str) -> str:
    query = urllib.parse.urlencode({"tags": tag_query})
    return f"{DANBOORU_ROOT}/posts?{query}"


def run_download(args: argparse.Namespace) -> int:
    tag_query = " ".join(args.tags).strip()
    if not tag_query:
        raise SystemExit("No Danbooru tags were provided.")

    config_path = build_gallery_dl_config(args, tag_query)
    command = ensure_gallery_dl_command()
    command.extend(["--config", str(config_path)])
    if args.limit:
        command.extend(["--range", f"1-{args.limit}"])
    command.append(danbooru_posts_url(tag_query))

    print("Config:", config_path)
    destination = (
        args.destination.expanduser().resolve(strict=False)
        if getattr(args, "destination", None)
        else args.root.resolve() / args.folder / (args.tag_folder or safe_segment(tag_query))
    )
    print("Output:", destination)
    print("Command:", subprocess.list2cmdline(command))

    if args.dry_run:
        config_path.unlink(missing_ok=True)
        return 0

    print("STAGE:download", flush=True)
    print(f"PROGRESS:0/{args.limit or 0}", flush=True)
    completed_count = 0
    try:
        process = subprocess.Popen(
            command,
            cwd=args.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            if line.startswith("GALLERY_PROGRESS:"):
                completed_count += 1
                print(f"PROGRESS:{completed_count}/{args.limit or completed_count}", flush=True)
            else:
                print(line, end="", flush=True)
        process.wait()
    finally:
        config_path.unlink(missing_ok=True)
    if process.returncode != 0 and command[:2] == [sys.executable, "-m"]:
        print(
            "\nCould not run gallery-dl as a Python module. Install it with:\n"
            "  python -m pip install gallery-dl\n",
            file=sys.stderr,
        )
    if process.returncode != 0:
        return process.returncode

    normalized, failed = normalize_gallery_dl_sidecars(destination, args)
    print(f"Normalized {normalized} downloaded sidecars ({failed} failed)")
    return 1 if failed else 0


def normalize_gallery_dl_sidecars(destination: Path, args: argparse.Namespace) -> tuple[int, int]:
    """Convert gallery-dl's flat Danbooru JSON into canonical central sidecars."""
    media = media_files([destination])
    candidates: list[tuple[Path, Path]] = []
    for media_path in media:
        raw_path = legacy_metadata_path_for(media_path, args.json_suffix)
        if raw_path.exists():
            candidates.append((media_path, raw_path))

    print("STAGE:metadata", flush=True)
    print(f"PROGRESS:0/{len(candidates)}", flush=True)
    normalized = 0
    failed = 0
    for index, (media_path, raw_path) in enumerate(candidates, 1):
        try:
            canonical_path = metadata_path_for(
                media_path, args.json_suffix, args.root, resolve_sidecar_dir(args)
            )
            if canonical_path.exists():
                print(f"PROGRESS:{index}/{len(candidates)}", flush=True)
                continue
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            if "post" in raw and "local_file" in raw:
                payload = raw
                payload["local_file"]["path"] = str(media_path)
            else:
                matched_md5 = str(raw.get("md5") or "")
                if not matched_md5:
                    matches = filename_md5s(media_path)
                    matched_md5 = matches[0] if matches else md5_file(media_path)
                payload = build_payload(media_path, raw, "gallery_dl", matched_md5)
            write_sidecars(media_path, payload, args)
            normalized += 1
        except Exception as exc:
            failed += 1
            print(f"Failed to normalize {raw_path}: {exc}", file=sys.stderr)
        print(f"PROGRESS:{index}/{len(candidates)}", flush=True)
    return normalized, failed


def split_tags(post: dict[str, Any]) -> dict[str, list[str]]:
    categories: dict[str, list[str]] = {}
    for category, field in TAG_FIELDS.items():
        raw = post.get(field) or ""
        categories[category] = [tag for tag in str(raw).split(" ") if tag]
    all_tags = post.get("tag_string") or ""
    categories["all"] = [tag for tag in str(all_tags).split(" ") if tag]
    return categories


def int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def relation_post_id(value: Any) -> int | None:
    if isinstance(value, dict):
        return int_or_none(value.get("id"))
    return int_or_none(value)


def child_post_ids(post: dict[str, Any]) -> list[int]:
    children = post.get("children")
    if not isinstance(children, list):
        return []

    ids: list[int] = []
    seen: set[int] = set()
    for child in children:
        child_id = relation_post_id(child)
        if child_id is None or child_id in seen:
            continue
        ids.append(child_id)
        seen.add(child_id)
    return ids


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_downloaded_at(path: Path) -> str | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    timestamp = getattr(stat, "st_birthtime", None) or getattr(stat, "st_ctime", None) or stat.st_mtime
    return datetime.fromtimestamp(timestamp).isoformat()


def filename_md5s(path: Path) -> list[str]:
    values: list[str] = []
    for match in MD5_RE.finditer(path.stem):
        value = match.group(1).lower()
        if value not in values:
            values.append(value)
    return values


def filename_post_id(path: Path) -> int | None:
    match = POST_ID_RE.match(path.stem)
    if not match:
        return None
    return int(match.group(1))


def md5_candidates(path: Path) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in filename_md5s(path):
        candidates.append(("filename_md5", value))
        seen.add(value)

    file_hash = md5_file(path)
    if file_hash.lower() not in seen:
        candidates.append(("file_md5", file_hash))
    return candidates


def request_json(
    endpoint: str,
    params: dict[str, str | int],
    username: str | None,
    api_key: str | None,
    retries: int,
    not_found_empty: bool = False,
) -> Any:
    url = f"{DANBOORU_ROOT}{endpoint}?{urllib.parse.urlencode(params)}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "danbooru-gallery-dl-helper/1.0",
    }
    if username and api_key:
        token = base64.b64encode(f"{username}:{api_key}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and not_found_empty:
                return []
            if exc.code == 429 and attempt < retries:
                wait_seconds = min(60 * (attempt + 1), 300)
                print(f"Rate limited by Danbooru; sleeping {wait_seconds}s")
                time.sleep(wait_seconds)
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise


def first_post(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict) and data.get("id"):
        return data
    return None


def find_post_by_md5(
    file_path: Path,
    username: str | None,
    api_key: str | None,
    retries: int,
    delay: float,
    known_md5: str | None = None,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    post_id = filename_post_id(file_path)
    if post_id is not None:
        data = request_json(
            f"/posts/{post_id}.json",
            {},
            username,
            api_key,
            retries,
            not_found_empty=True,
        )
        if delay:
            time.sleep(delay)
        if post := first_post(data):
            return post, "filename_post_id", str(post_id)

    last_md5 = None
    candidates = [("indexed_md5", known_md5)] if known_md5 else md5_candidates(file_path)
    for method, md5_value in candidates:
        if not md5_value:
            continue
        last_md5 = md5_value
        data = request_json(
            "/posts.json",
            {"md5": md5_value, "limit": 1},
            username,
            api_key,
            retries,
            not_found_empty=True,
        )
        if delay:
            time.sleep(delay)
        if post := first_post(data):
            return post, method, md5_value
    return None, None, last_md5


def add_extra_metadata(
    post: dict[str, Any],
    includes: list[str],
    username: str | None,
    api_key: str | None,
    retries: int,
    delay: float,
) -> dict[str, Any]:
    if not includes or not post.get("id"):
        return post
    data = request_json(
        f"/posts/{post['id']}.json",
        {
            "only": ",".join([*includes, "id"]),
        },
        username,
        api_key,
        retries,
    )
    if delay:
        time.sleep(delay)
    if extra_post := first_post(data):
        merged = dict(post)
        merged.update(extra_post)
        return merged
    return post


def media_files(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            found.append(path)
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file() and child.suffix.lower() in MEDIA_EXTENSIONS:
                    found.append(child)
    return sorted(found, key=lambda item: str(item).casefold())


def filter_media_files(files: list[Path], args: argparse.Namespace) -> list[Path]:
    if getattr(args, "filename_md5_only", False):
        files = [path for path in files if filename_md5s(path)]
    if getattr(args, "gallery_dl_names_only", False):
        files = [path for path in files if path.stem.startswith("__") and "__" in path.stem[2:]]
    return files


def resolve_sidecar_dir(args: argparse.Namespace) -> Path:
    return resolve_project_path(args.sidecar_dir).resolve()


def legacy_metadata_path_for(media_path: Path, suffix: str) -> Path:
    return media_path.with_name(media_path.name + suffix)


def metadata_path_for(
    media_path: Path,
    suffix: str,
    root: Path | None = None,
    sidecar_dir: Path | None = None,
) -> Path:
    if root is None or sidecar_dir is None:
        return legacy_metadata_path_for(media_path, suffix)

    return canonical_sidecar_path(media_path, suffix, root, sidecar_dir, _LIBRARY_ROOTS)


def sidecar_candidates_for(media_path: Path, suffix: str, root: Path, sidecar_dir: Path) -> list[Path]:
    return layout_sidecar_candidates(media_path, suffix, root, sidecar_dir, _LIBRARY_ROOTS)


def existing_metadata_path_for(media_path: Path, suffix: str, root: Path, sidecar_dir: Path) -> Path | None:
    for candidate in sidecar_candidates_for(media_path, suffix, root, sidecar_dir):
        if candidate.exists():
            return candidate
    return None


def media_path_for_sidecar(sidecar_path: Path, suffix: str, root: Path, sidecar_dir: Path) -> Path | None:
    media_name = sidecar_path.name.removesuffix(suffix)
    if not media_name or media_name == sidecar_path.name:
        return None

    resolved_sidecar = sidecar_path.resolve(strict=False)
    try:
        relative_sidecar = resolved_sidecar.relative_to(sidecar_dir.resolve(strict=False))
    except ValueError:
        return sidecar_path.with_name(media_name)

    # External media sidecars live below data/sidecars/_outside_root/<hash>.
    # Their canonical JSON records the real absolute media path; reconstructing
    # it relative to root would incorrectly classify every one as an orphan.
    if relative_sidecar.parts and relative_sidecar.parts[0] == "_outside_root":
        metadata_path = sidecar_path
        if suffix != ".danbooru.json":
            metadata_path = sidecar_path.with_name(media_name + ".danbooru.json")
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            local_path = payload.get("local_file", {}).get("path")
            if local_path:
                return Path(local_path)
        except (OSError, ValueError, TypeError, AttributeError):
            return None
    if len(relative_sidecar.parts) >= 3 and relative_sidecar.parts[0] == "roots":
        root_id = relative_sidecar.parts[1]
        relative_parent = Path(*relative_sidecar.parts[2:-1]) if len(relative_sidecar.parts) > 3 else Path()
        if root_id == "portable-root":
            return root / relative_parent / media_name
        library_root = next((item for item in _LIBRARY_ROOTS if item.root_id == root_id), None)
        if library_root is not None:
            return library_root.path / relative_parent / media_name
        # Unregistered-root sidecars deliberately keep their absolute durable
        # identity in JSON because a path cannot be reconstructed from a hash.
        metadata_path = sidecar_path if suffix == ".danbooru.json" else sidecar_path.with_name(media_name + ".danbooru.json")
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            local_path = payload.get("local_file", {}).get("path")
            return Path(local_path) if local_path else None
        except (OSError, ValueError, TypeError, AttributeError):
            return None
    return root / relative_sidecar.parent / media_name


def default_sidecar_archive_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return project_root() / "data" / "sidecar_archive" / stamp


def resolve_sidecar_archive_dir(args: argparse.Namespace) -> Path:
    archive_dir = args.sidecar_archive_dir or default_sidecar_archive_dir()
    return resolve_project_path(archive_dir).resolve()


def archive_existing_sidecars(media_path: Path, args: argparse.Namespace, archive_dir: Path | None) -> int:
    if archive_dir is None:
        return 0

    sidecar_dir = resolve_sidecar_dir(args)
    archived = 0
    for suffix in (args.json_suffix, args.tags_suffix):
        for sidecar_path in sidecar_candidates_for(media_path, suffix, args.root, sidecar_dir):
            if not sidecar_path.exists():
                continue
            try:
                relative_path = sidecar_path.resolve().relative_to(args.root.resolve())
            except ValueError:
                try:
                    relative_path = Path("_central_sidecars") / sidecar_path.resolve().relative_to(sidecar_dir)
                except ValueError:
                    digest = hashlib.sha256(str(sidecar_path).encode("utf-8")).hexdigest()[:16]
                    relative_path = Path("_outside_root") / digest / sidecar_path.name
            target_path = archive_dir / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sidecar_path, target_path)
            archived += 1
    return archived


def build_payload(
    media_path: Path,
    post: dict[str, Any],
    matched_by: str,
    matched_md5: str,
    local_md5: str | None = None,
) -> dict[str, Any]:
    tags = split_tags(post)
    return {
        "source": "danbooru",
        "post_url": f"{DANBOORU_ROOT}/posts/{post.get('id')}",
        "matched_by": matched_by,
        "matched_md5": matched_md5,
        "local_file": {
            "path": str(media_path),
            "name": media_path.name,
            "size": media_path.stat().st_size,
            "md5": local_md5 or md5_file(media_path),
            "downloaded_at": local_downloaded_at(media_path),
        },
        "tags": tags,
        "post": post,
    }


def write_sidecars(
    media_path: Path,
    payload: dict[str, Any],
    args: argparse.Namespace,
    archive_dir: Path | None = None,
) -> int:
    tags = payload["tags"]
    sidecar_dir = resolve_sidecar_dir(args)
    metadata_path = metadata_path_for(media_path, args.json_suffix, args.root, sidecar_dir)
    tags_path = metadata_path_for(media_path, args.tags_suffix, args.root, sidecar_dir)
    archived = archive_existing_sidecars(media_path, args, archive_dir)

    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    tags_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    tags_path.write_text("\n".join(tags["all"]) + "\n", encoding="utf-8")
    return archived


def default_backfill_paths(root: Path) -> list[Path]:
    paths = []
    for folder in DEFAULT_SCAN_FOLDERS:
        path = root / folder
        if path.exists():
            paths.append(path)
    return paths or [root]


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    """Read dimensions without printing Pillow's harmless corrupt-EXIF warning."""
    if _PILImage is None:
        return None, None
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Corrupt EXIF data\..*",
            category=UserWarning,
        )
        with _PILImage.open(path) as image:
            return image.size


def default_sidecar_scan_paths(root: Path, sidecar_dir: Path) -> list[Path]:
    return [sidecar_dir, *default_backfill_paths(root)]


def sidecar_files(
    paths: list[Path],
    suffix: str,
    root: Path | None = None,
    sidecar_dir: Path | None = None,
) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            return
        seen.add(resolved)
        found.append(path)

    for path in paths:
        if path.is_file() and path.name.endswith(suffix):
            add(path)
        elif root is not None and sidecar_dir is not None and path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            for sidecar_path in sidecar_candidates_for(path, suffix, root, sidecar_dir):
                if sidecar_path.exists():
                    add(sidecar_path)
        elif path.is_dir():
            for child in path.rglob(f"*{suffix}"):
                if child.is_file():
                    add(child)
            if root is not None and sidecar_dir is not None:
                try:
                    relative_path = path.resolve(strict=False).relative_to(root.resolve(strict=False))
                except ValueError:
                    continue
                central_path = sidecar_dir / relative_path
                if central_path.exists() and central_path.resolve(strict=False) != path.resolve(strict=False):
                    for child in central_path.rglob(f"*{suffix}"):
                        if child.is_file():
                            add(child)
    return sorted(found, key=lambda item: str(item).casefold())


def orphan_sidecar_files(paths: list[Path], suffixes: list[str], root: Path, sidecar_dir: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for suffix in suffixes:
        for sidecar_path in sidecar_files(paths, suffix, root, sidecar_dir):
            media_path = media_path_for_sidecar(sidecar_path, suffix, root, sidecar_dir)
            if media_path is None:
                continue
            if media_path.exists():
                continue
            resolved_media = media_path.resolve(strict=False)
            resolved_root = root.resolve(strict=False)
            try:
                relative_media = resolved_media.relative_to(resolved_root)
            except ValueError:
                media_root = Path(resolved_media.anchor) if resolved_media.anchor else resolved_media.parent
            else:
                media_root = resolved_root / relative_media.parts[0] if relative_media.parts else resolved_root
            if not media_root.exists():
                print(f"Skipping sidecar on unavailable media root: {sidecar_path}")
                continue
            resolved = sidecar_path.resolve()
            if resolved not in seen:
                found.append(sidecar_path)
                seen.add(resolved)
    return sorted(found, key=lambda item: str(item).casefold())


def compact_index_record(payload: dict[str, Any]) -> dict[str, Any]:
    post = payload.get("post") or {}
    local_file = payload.get("local_file") or {}
    tags = payload.get("tags") or {}
    return {
        "path": local_file.get("path"),
        "file": local_file.get("name"),
        "size": local_file.get("size"),
        "local_md5": local_file.get("md5"),
        "downloaded_at": local_file.get("downloaded_at"),
        "matched_by": payload.get("matched_by"),
        "matched_md5": payload.get("matched_md5"),
        "post_id": post.get("id"),
        "post_url": payload.get("post_url"),
        "rating": post.get("rating"),
        "score": post.get("score"),
        "source_url": post.get("source"),
        "created_at": post.get("created_at"),
        "updated_at": post.get("updated_at"),
        "parent_id": int_or_none(post.get("parent_id")) or relation_post_id(post.get("parent")),
        "has_children": bool(post.get("has_children") or child_post_ids(post)),
        "child_ids": child_post_ids(post),
        "width": post.get("image_width"),
        "height": post.get("image_height"),
        "file_ext": post.get("file_ext"),
        "tags": tags,
    }


def open_index(args: argparse.Namespace):
    if not args.index_jsonl:
        return None
    index_path = args.index_jsonl
    if not index_path.is_absolute():
        index_path = args.root / index_path
    index_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if args.append_index else "w"
    return index_path.open(mode, encoding="utf-8")


def emit_file_status(
    media_path: Path,
    status: str,
    index: int,
    total: int,
    detail: str = "",
) -> None:
    print(
        "FILE_STATUS:" + json.dumps(
            {
                "path": str(media_path),
                "filename": media_path.name,
                "status": status,
                "index": index,
                "total": total,
                "detail": detail,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def update_metadata_ingest_state(
    connection: sqlite3.Connection | None,
    media_path: Path,
    status: str,
    error: str | None = None,
) -> None:
    if connection is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    if status == "matched":
        connection.execute(
            """
            UPDATE ingest_state
               SET phase='metadata', status='done', error=NULL, metadata_at=?
             WHERE media_path=?
            """,
            (now, str(media_path)),
        )
    else:
        connection.execute(
            """
            UPDATE ingest_state
               SET phase='metadata', status=?, error=?
             WHERE media_path=?
            """,
            (status, (error or "")[:1000], str(media_path)),
        )


def run_backfill(args: argparse.Namespace) -> int:
    username = args.username or os.environ.get("DANBOORU_USERNAME")
    api_key = args.api_key or os.environ.get("DANBOORU_API_KEY")
    includes = parse_includes(args.metadata_includes) if args.extra_metadata else []
    sidecar_dir = resolve_sidecar_dir(args)
    indexed_md5s: dict[str, str] = {}
    state_connection: sqlite3.Connection | None = None
    if getattr(args, "use_indexed_md5", False):
        database_path = resolve_database_path(args.root, args.database)
        if database_path.exists():
            with closing(sqlite3.connect(database_path)) as indexed_connection:
                indexed_md5s = {
                    os.path.normcase(str(path)): str(local_md5)
                    for path, local_md5 in indexed_connection.execute(
                        "SELECT path, local_md5 FROM files WHERE local_md5 IS NOT NULL AND local_md5<>''"
                    )
                }
            state_connection = connect_sqlite_live(database_path)
            init_sqlite(state_connection)

    scan_paths = [path.resolve() for path in args.paths] if args.paths else default_backfill_paths(args.root)
    files = filter_media_files(media_files(scan_paths), args)
    if args.limit:
        files = files[: args.limit]

    need_processing = []
    skip_count = 0
    for media_path in files:
        metadata_path = existing_metadata_path_for(media_path, args.json_suffix, args.root, sidecar_dir)
        if metadata_path is not None and not args.overwrite:
            skip_count += 1
        else:
            need_processing.append(media_path)

    total = len(need_processing)
    print(f"Scanning {len(files)} media files ({total} need processing, {skip_count} already have metadata)")
    print("STAGE:metadata", flush=True)
    print(f"PROGRESS:0/{total}", flush=True)

    if args.dry_run:
        for media_path in need_processing[:20]:
            print("Would inspect:", media_path)
        if len(need_processing) > 20:
            print(f"... and {len(need_processing) - 20} more")
        if state_connection is not None:
            state_connection.close()
        return 0

    matched = 0
    skipped = skip_count
    missed = 0
    failed = 0
    archived = 0
    archive_dir = None
    if args.overwrite and args.archive_replaced_sidecars:
        archive_dir = resolve_sidecar_archive_dir(args)
        archive_dir.mkdir(parents=True, exist_ok=True)
        print(f"Archiving replaced sidecars to {archive_dir}")

    index_context = open_index(args)
    if index_context is None:
        index_context = nullcontext(None)

    try:
        with index_context as index_file:
            for index, media_path in enumerate(need_processing, 1):
                emit_file_status(media_path, "working", index, total)
                print(f"[{index}/{total}] {media_path.name}")
                try:
                    post, matched_by, matched_md5 = find_post_by_md5(
                        media_path,
                        username,
                        api_key,
                        args.retries,
                        args.delay,
                        indexed_md5s.get(os.path.normcase(str(media_path))),
                    )
                    if not post:
                        missed += 1
                        detail = "No Danbooru MD5 match"
                        update_metadata_ingest_state(state_connection, media_path, "no_match", detail)
                        emit_file_status(media_path, "no_match", index, total, detail)
                        print("  no Danbooru md5 match")
                    else:
                        post = add_extra_metadata(post, includes, username, api_key, args.retries, args.delay)
                        payload = build_payload(
                            media_path,
                            post,
                            matched_by or "unknown",
                            matched_md5 or "",
                            indexed_md5s.get(os.path.normcase(str(media_path))),
                        )
                        archived += write_sidecars(media_path, payload, args, archive_dir)
                        if index_file:
                            index_file.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
                            index_file.flush()
                        matched += 1
                        detail = f"Post {post.get('id')} via {matched_by or 'unknown'}"
                        update_metadata_ingest_state(state_connection, media_path, "matched")
                        emit_file_status(media_path, "matched", index, total, detail)
                        print(f"  matched post {post.get('id')} by {matched_by}")
                except Exception as exc:  # noqa: BLE001 - keep long batches moving.
                    failed += 1
                    detail = str(exc)
                    update_metadata_ingest_state(state_connection, media_path, "error", detail)
                    emit_file_status(media_path, "error", index, total, detail)
                    print(f"  failed: {exc}", file=sys.stderr)
                if state_connection is not None and (index % 25 == 0 or index == total):
                    state_connection.commit()
                print(f"PROGRESS:{index}/{total}", flush=True)
    finally:
        if state_connection is not None:
            state_connection.commit()
            state_connection.close()

    print(
        "Done: "
        f"{matched} matched, {missed} missed, {skipped} skipped, {failed} failed, "
        f"{archived} sidecars archived"
    )
    return 1 if failed else 0


def run_index(args: argparse.Namespace) -> int:
    sidecar_dir = resolve_sidecar_dir(args)
    scan_paths = [path.resolve() for path in args.paths] if args.paths else default_sidecar_scan_paths(args.root, sidecar_dir)
    sidecars = sidecar_files(scan_paths, args.json_suffix, args.root, sidecar_dir)
    if args.limit:
        sidecars = sidecars[: args.limit]

    records: list[dict[str, Any]] = []
    skipped = 0
    for sidecar_path in sidecars:
        try:
            payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            skipped += 1
            print(f"Skipping {sidecar_path}: {exc}", file=sys.stderr)
            continue
        records.append(payload if args.full else compact_index_record(payload))

    output = args.output
    if not output.is_absolute():
        output = args.root / output
    output.parent.mkdir(parents=True, exist_ok=True)

    index = {
        "source": "danbooru-local-index",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "records": records,
    }
    dump_kwargs: dict[str, Any] = {"ensure_ascii": False}
    if args.pretty:
        dump_kwargs["indent"] = 2
    else:
        dump_kwargs["separators"] = (",", ":")
    output.write_text(json.dumps(index, **dump_kwargs) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} records to {output}")
    if skipped:
        print(f"Skipped {skipped} unreadable sidecars")
    return 0


def run_clean_sidecars(args: argparse.Namespace) -> int:
    sidecar_dir = resolve_sidecar_dir(args)
    scan_paths = [path.resolve() for path in args.paths] if args.paths else default_sidecar_scan_paths(args.root, sidecar_dir)
    sidecars = orphan_sidecar_files(scan_paths, [args.json_suffix, args.tags_suffix], args.root, sidecar_dir)
    if args.limit:
        sidecars = sidecars[: args.limit]

    total = len(sidecars)
    deleted = 0
    failed = 0
    print(f"Found {total} orphan sidecar file(s)")
    print(f"PROGRESS:0/{total}", flush=True)

    for index, sidecar_path in enumerate(sidecars, 1):
        try:
            print(("Would delete: " if args.dry_run else "Deleting: ") + str(sidecar_path))
            if not args.dry_run:
                sidecar_path.unlink()
                deleted += 1
        except OSError as exc:
            failed += 1
            print(f"Failed to delete {sidecar_path}: {exc}", file=sys.stderr)
        if index % 1000 == 0 or index == total:
            print(f"PROGRESS:{index}/{total}", flush=True)

    if args.dry_run:
        print(f"Dry run complete: {total} orphan sidecar file(s) would be deleted")
    else:
        print(f"Deleted {deleted} orphan sidecar file(s)")
    if failed:
        print(f"Failed to delete {failed} sidecar file(s)")
    return 1 if failed else 0


def create_sqlite_indexes(connection: sqlite3.Connection) -> None:
    create_data_indexes(connection)


def init_sqlite(connection: sqlite3.Connection, create_indexes: bool = True) -> None:
    ensure_data_schema(connection, create_indexes=create_indexes)


def connect_sqlite(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    # The database is a rebuildable index, so disable journaling. This also
    # avoids Windows disk/locking failures on some external or synced folders.
    connection.execute("PRAGMA journal_mode = OFF")
    connection.execute("PRAGMA synchronous = OFF")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.execute("PRAGMA cache_size = -65536")
    return connection


def tag_category_map(tags: dict[str, Any]) -> dict[str, str]:
    categories: dict[str, str] = {}
    for category in ("artist", "character", "copyright", "general", "meta"):
        for tag in tags.get(category) or []:
            categories[str(tag)] = category
    for tag in tags.get("all") or []:
        categories.setdefault(str(tag), "unknown")
    return categories


def upsert_tag(
    connection: sqlite3.Connection,
    name: str,
    category: str,
    tag_cache: dict[str, tuple[int, str]],
) -> int:
    cached = tag_cache.get(name)
    if cached:
        tag_id, cached_category = cached
        if cached_category == "unknown" and category != "unknown":
            connection.execute("UPDATE tags SET category = ? WHERE id = ?", (category, tag_id))
            tag_cache[name] = (tag_id, category)
        return tag_id

    row = connection.execute(
        """
        INSERT INTO tags (name, category)
        VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET category = excluded.category
        RETURNING id, category
        """,
        (name, category),
    ).fetchone()
    tag_id = int(row[0])
    tag_cache[name] = (tag_id, str(row[1]))
    return tag_id


def folder_for_media(
    media_path: Path,
    root: Path,
    extra_roots: dict[str, str] | None = None,
) -> str:
    """Folder label for a media file: relative to the project root, or, for a
    registered external folder, the folder's display name plus any subpath."""
    parent = media_path.parent
    try:
        return str(parent.relative_to(root))
    except ValueError:
        pass
    for extra_root_text, display_name in (extra_roots or {}).items():
        try:
            relative = parent.relative_to(Path(extra_root_text))
        except ValueError:
            continue
        return display_name if str(relative) == "." else str(Path(display_name) / relative)
    return str(parent)


def import_payload_to_sqlite(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    root: Path,
    tag_cache: dict[str, tuple[int, str]],
    store_raw_json: bool,
    extra_roots: dict[str, str] | None = None,
) -> None:
    post = payload.get("post") or {}
    local_file = payload.get("local_file") or {}
    tags = payload.get("tags") or split_tags(post)
    path_value = local_file.get("path")
    if not path_value:
        raise ValueError("sidecar payload is missing local_file.path")
    file_path = Path(str(path_value))
    downloaded_at = local_file.get("downloaded_at")
    if not downloaded_at and file_path.exists():
        downloaded_at = local_downloaded_at(file_path)

    folder = folder_for_media(file_path, root, extra_roots)
    root_id, relative_path = identity_for_media(file_path, root, _LIBRARY_ROOTS)

    row = connection.execute(
        """
        INSERT INTO files (
            path, folder, root_id, relative_path, name, ext, size, local_md5, downloaded_at, matched_md5, matched_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            folder = excluded.folder,
            root_id = excluded.root_id,
            relative_path = excluded.relative_path,
            name = excluded.name,
            ext = excluded.ext,
            size = excluded.size,
            local_md5 = excluded.local_md5,
            downloaded_at = excluded.downloaded_at,
            matched_md5 = excluded.matched_md5,
            matched_by = excluded.matched_by
        RETURNING id
        """,
        (
            str(file_path),
            folder,
            root_id,
            str(relative_path),
            local_file.get("name") or file_path.name,
            file_path.suffix.lower().lstrip("."),
            local_file.get("size"),
            local_file.get("md5"),
            downloaded_at,
            payload.get("matched_md5"),
            payload.get("matched_by"),
        ),
    ).fetchone()
    file_id = int(row[0])
    parent_id = int_or_none(post.get("parent_id")) or relation_post_id(post.get("parent"))
    child_ids = child_post_ids(post)
    has_children = 1 if post.get("has_children") or child_ids else 0

    row = connection.execute(
        """
        INSERT INTO posts (
            file_id, danbooru_post_id, post_url, rating, score, source_url,
            created_at, updated_at, parent_id, has_children, child_ids_json,
            width, height, file_ext, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            danbooru_post_id = excluded.danbooru_post_id,
            post_url = excluded.post_url,
            rating = excluded.rating,
            score = excluded.score,
            source_url = excluded.source_url,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at,
            parent_id = excluded.parent_id,
            has_children = excluded.has_children,
            child_ids_json = excluded.child_ids_json,
            width = excluded.width,
            height = excluded.height,
            file_ext = excluded.file_ext,
            raw_json = excluded.raw_json
        RETURNING id
        """,
        (
            file_id,
            post.get("id"),
            payload.get("post_url"),
            post.get("rating"),
            post.get("score"),
            post.get("source"),
            post.get("created_at"),
            post.get("updated_at"),
            parent_id,
            has_children,
            json.dumps(child_ids) if child_ids else None,
            post.get("image_width"),
            post.get("image_height"),
            post.get("file_ext"),
            json.dumps(payload, sort_keys=True, ensure_ascii=False) if store_raw_json else None,
        ),
    ).fetchone()
    post_row_id = int(row[0])
    connection.execute("DELETE FROM post_tags WHERE post_id = ?", (post_row_id,))

    post_tags: list[tuple[int, int]] = []
    for tag, category in tag_category_map(tags).items():
        tag_id = upsert_tag(connection, tag, category, tag_cache)
        post_tags.append((post_row_id, tag_id))
    connection.executemany(
        "INSERT OR IGNORE INTO post_tags (post_id, tag_id) VALUES (?, ?)",
        post_tags,
    )


def resolve_database_path(root: Path, database: Path) -> Path:
    if database.is_absolute():
        return database
    return root / database


def extra_roots_map(paths: list[Path]) -> dict[str, str]:
    """Map resolved external folder path -> display name (folder basename)."""
    mapping: dict[str, str] = {}
    for path in paths:
        resolved = path.expanduser().resolve(strict=False)
        mapping[str(resolved)] = resolved.name
    return mapping


def upsert_manifest_row(
    connection: sqlite3.Connection,
    media_path_text: str,
    sidecar_path_text: str | None,
    sidecar_mtime: int | None,
    sidecar_size: int | None,
    media_mtime: int | None,
    media_size: int | None,
) -> None:
    connection.execute(
        """
        INSERT INTO sync_manifest (
            media_path, sidecar_path, sidecar_mtime, sidecar_size,
            media_mtime, media_size, synced_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(media_path) DO UPDATE SET
            sidecar_path = excluded.sidecar_path,
            sidecar_mtime = excluded.sidecar_mtime,
            sidecar_size = excluded.sidecar_size,
            media_mtime = excluded.media_mtime,
            media_size = excluded.media_size,
            synced_at = excluded.synced_at
        """,
        (
            media_path_text,
            sidecar_path_text,
            sidecar_mtime,
            sidecar_size,
            media_mtime,
            media_size,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def record_manifest(
    connection: sqlite3.Connection,
    media_path: Path,
    sidecar_path: Path,
    media_stat: os.stat_result | None,
) -> None:
    try:
        sidecar_stat = sidecar_path.stat()
    except OSError:
        sidecar_stat = None
    upsert_manifest_row(
        connection,
        str(media_path),
        str(sidecar_path),
        sidecar_stat.st_mtime_ns if sidecar_stat else None,
        sidecar_stat.st_size if sidecar_stat else None,
        media_stat.st_mtime_ns if media_stat else None,
        media_stat.st_size if media_stat else None,
    )


def run_sqlite(args: argparse.Namespace) -> int:
    sidecar_dir = resolve_sidecar_dir(args)
    extra_roots = extra_roots_map(getattr(args, "extra_root", None) or [])
    scan_paths = [path.resolve() for path in args.paths] if args.paths else default_sidecar_scan_paths(args.root, sidecar_dir)
    sidecars = sidecar_files(scan_paths, args.json_suffix, args.root, sidecar_dir)
    if args.limit:
        sidecars = sidecars[: args.limit]

    database_path = resolve_database_path(args.root, args.output)
    if args.replace and database_path.exists():
        database_path.unlink()

    total = len(sidecars)
    imported = 0
    skipped = 0
    missing_media = 0
    tag_cache: dict[str, tuple[int, str]] = {}
    defer_indexes = args.replace
    print(f"PROGRESS:0/{total}", flush=True)
    with connect_sqlite(database_path) as connection:
        init_sqlite(connection, create_indexes=not defer_indexes)
        connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("generated_at", datetime.now(timezone.utc).isoformat()),
        )
        connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("source_root", str(args.root)),
        )
        for i, sidecar_path in enumerate(sidecars, 1):
            try:
                payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
                local_file = payload.get("local_file") or {}
                path_value = local_file.get("path")
                if not path_value:
                    raise ValueError("sidecar payload is missing local_file.path")
                media_path = Path(str(path_value))
                try:
                    media_stat = media_path.stat()
                except OSError:
                    media_stat = None
                if args.skip_missing_media and media_stat is None:
                    missing_media += 1
                    continue
                import_payload_to_sqlite(
                    connection,
                    payload,
                    args.root,
                    tag_cache,
                    store_raw_json=not args.no_raw_json,
                    extra_roots=extra_roots,
                )
                record_manifest(connection, media_path, sidecar_path, media_stat)
                imported += 1
            except (OSError, json.JSONDecodeError, ValueError, sqlite3.Error) as exc:
                skipped += 1
                print(f"Skipping {sidecar_path}: {exc}", file=sys.stderr)
            if i % 50 == 0 or i == total:
                print(f"PROGRESS:{i}/{total}", flush=True)
            if args.commit_every > 0 and imported and imported % args.commit_every == 0:
                connection.commit()

        connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("record_count", str(imported)),
        )
        connection.commit()
        if defer_indexes:
            print("Creating indexes...", flush=True)
            create_sqlite_indexes(connection)
            connection.commit()

    print(f"Wrote {imported} records to {database_path}")
    if missing_media:
        print(f"Skipped {missing_media} sidecars whose media file is missing")
    if skipped:
        print(f"Skipped {skipped} unreadable sidecars")
    if not sidecars:
        print("No sidecars found. Run the backfill command first to create .danbooru.json files.")
    return 0


# ---------------------------------------------------------------------------
# sync: incremental media/sidecar -> SQLite delta import (no full rebuild)
# ---------------------------------------------------------------------------

SYNC_SKIP_DIR_NAMES = {"data", "_danbooru_metadata", "_gallery-dl", "node_modules"}


def connect_sqlite_live(database_path: Path) -> sqlite3.Connection:
    """Connect for incremental updates against a database the app may be serving."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=60)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA temp_store = MEMORY")
    connection.execute("PRAGMA cache_size = -65536")
    return connection


def scan_media_tree(
    root: Path,
    json_suffix: str,
    skip_special_dirs: bool = True,
) -> tuple[dict[str, tuple[int, int]], dict[str, tuple[int, int]]]:
    """os.scandir walk returning ({media_path: (mtime_ns, size)}, {sidecar_path: ...}).

    Stat info comes from the directory listing itself on Windows, so a
    no-change pass never opens a single file.
    """
    media: dict[str, tuple[int, int]] = {}
    sidecars: dict[str, tuple[int, int]] = {}
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            iterator = os.scandir(current)
        except OSError:
            continue
        with iterator:
            for entry in iterator:
                name = entry.name
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if name.startswith("."):
                            continue
                        if skip_special_dirs and name in SYNC_SKIP_DIR_NAMES:
                            continue
                        stack.append(entry.path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if name.endswith(json_suffix):
                        stat = entry.stat()
                        sidecars[entry.path] = (stat.st_mtime_ns, stat.st_size)
                        continue
                    dot = name.rfind(".")
                    if dot != -1 and name[dot:].lower() in MEDIA_EXTENSIONS:
                        stat = entry.stat()
                        media[entry.path] = (stat.st_mtime_ns, stat.st_size)
                except OSError:
                    continue
    return media, sidecars


def import_minimal_media(
    connection: sqlite3.Connection,
    media_path: Path,
    folder: str,
    size: int,
    root: Path,
) -> None:
    """Index sidecar-less media as visibly Unrated rather than General."""
    downloaded_at = local_downloaded_at(media_path)
    ext = media_path.suffix.lower().lstrip(".")
    width = height = None
    if _PILImage is not None and ext not in {"mp4", "webm"}:
        try:
            width, height = image_dimensions(media_path)
        except Exception:
            width = height = None

    local_md5 = md5_file(media_path)
    root_id, relative_path = identity_for_media(media_path, root, _LIBRARY_ROOTS)
    row = connection.execute(
        """
        INSERT INTO files (
            path, folder, root_id, relative_path, name, ext, size, local_md5, downloaded_at, matched_md5, matched_by
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
        ON CONFLICT(path) DO UPDATE SET
            folder = excluded.folder,
            root_id = excluded.root_id,
            relative_path = excluded.relative_path,
            name = excluded.name,
            ext = excluded.ext,
            size = excluded.size,
            local_md5 = excluded.local_md5,
            downloaded_at = excluded.downloaded_at,
            matched_md5 = excluded.matched_md5,
            matched_by = excluded.matched_by
        RETURNING id
        """,
        (str(media_path), folder, root_id, str(relative_path), media_path.name, ext, size, local_md5, downloaded_at),
    ).fetchone()
    file_id = int(row[0])

    post_row = connection.execute(
        """
        INSERT INTO posts (
            file_id, danbooru_post_id, post_url, rating, score, source_url,
            created_at, updated_at, parent_id, has_children, child_ids_json,
            width, height, file_ext, raw_json
        )
        VALUES (?, NULL, NULL, 'u', NULL, NULL, ?, NULL, NULL, 0, NULL, ?, ?, ?, NULL)
        ON CONFLICT(file_id) DO UPDATE SET
            danbooru_post_id = excluded.danbooru_post_id,
            post_url = excluded.post_url,
            rating = excluded.rating,
            score = excluded.score,
            source_url = excluded.source_url,
            created_at = excluded.created_at,
            updated_at = excluded.updated_at,
            parent_id = excluded.parent_id,
            has_children = excluded.has_children,
            child_ids_json = excluded.child_ids_json,
            width = excluded.width,
            height = excluded.height,
            file_ext = excluded.file_ext,
            raw_json = excluded.raw_json
        RETURNING id
        """,
        (file_id, downloaded_at, width, height, ext),
    ).fetchone()
    connection.execute("DELETE FROM post_tags WHERE post_id = ?", (int(post_row[0]),))


def _import_scan_roots(args: argparse.Namespace) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for raw in (args.paths or default_backfill_paths(args.root)):
        path = raw.expanduser().resolve(strict=False)
        key = os.path.normcase(str(path))
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        roots.append(path)
    return roots


def _path_in_roots(path_text: str, roots: list[Path]) -> bool:
    resolved = Path(path_text).resolve(strict=False)
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def run_import_discover(args: argparse.Namespace) -> int:
    """Phase 1: make files browseable using directory metadata only."""
    roots = _import_scan_roots(args)
    if not roots:
        print("No folders to discover.")
        return 0
    found: dict[str, tuple[int, int]] = {}
    for root in roots:
        media, _ = scan_media_tree(root, ".danbooru.json")
        found.update(media)
    total = len(found)
    print("STAGE:discover", flush=True)
    print(f"PROGRESS:0/{total}", flush=True)
    database_path = resolve_database_path(args.root, args.output)
    extra_roots = extra_roots_map(roots)
    with closing(connect_sqlite_live(database_path)) as connection:
        init_sqlite(connection)
        for index, (path_text, (mtime, size)) in enumerate(found.items(), 1):
            media_path = Path(path_text)
            root_id, relative_path = identity_for_media(media_path, args.root, _LIBRARY_ROOTS)
            folder = folder_for_media(media_path, args.root, extra_roots)
            downloaded_at = local_downloaded_at(media_path)
            row = connection.execute(
                """
                INSERT INTO files (
                    path, folder, root_id, relative_path, name, ext, size,
                    local_md5, downloaded_at, matched_md5, matched_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, NULL)
                ON CONFLICT(path) DO UPDATE SET
                    folder=excluded.folder,
                    root_id=excluded.root_id,
                    relative_path=excluded.relative_path,
                    name=excluded.name,
                    ext=excluded.ext,
                    size=excluded.size,
                    downloaded_at=COALESCE(files.downloaded_at, excluded.downloaded_at)
                RETURNING id
                """,
                (
                    path_text, folder, root_id, str(relative_path), media_path.name,
                    media_path.suffix.lower().lstrip("."), size, downloaded_at,
                ),
            ).fetchone()
            file_id = int(row[0])
            connection.execute(
                """
                INSERT INTO posts (
                    file_id, rating, created_at, has_children, file_ext
                ) VALUES (?, 'u', ?, 0, ?)
                ON CONFLICT(file_id) DO UPDATE SET file_ext=excluded.file_ext
                """,
                (file_id, downloaded_at, media_path.suffix.lower().lstrip(".")),
            )
            connection.execute(
                """
                INSERT INTO ingest_state (
                    media_path, root_id, relative_path, phase, status, discovered_at
                ) VALUES (?, ?, ?, 'discovered', 'done', ?)
                ON CONFLICT(media_path) DO UPDATE SET
                    root_id=excluded.root_id,
                    relative_path=excluded.relative_path,
                    discovered_at=COALESCE(ingest_state.discovered_at, excluded.discovered_at)
                """,
                (path_text, root_id, str(relative_path), datetime.now(timezone.utc).isoformat()),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO sync_manifest (
                    media_path, sidecar_path, sidecar_mtime, sidecar_size,
                    media_mtime, media_size, synced_at
                ) VALUES (?, NULL, NULL, NULL, ?, ?, ?)
                """,
                (path_text, mtime, size, datetime.now(timezone.utc).isoformat()),
            )
            if index % 500 == 0:
                connection.commit()
            if index % 100 == 0 or index == total:
                print(f"PROGRESS:{index}/{total}", flush=True)
        connection.commit()
    print(f"Discovered {total} media files without opening their contents.")
    return 0


def _enrich_file(path_text: str) -> tuple[str, str, int | None, int | None, str | None]:
    path = Path(path_text)
    try:
        local_md5 = md5_file(path)
        width = height = None
        if _PILImage is not None and path.suffix.lower() not in {".mp4", ".webm"}:
            width, height = image_dimensions(path)
        return path_text, local_md5, width, height, None
    except Exception as exc:  # noqa: BLE001 - one damaged file must not stop the phase.
        return path_text, "", None, None, str(exc)


def run_import_enrich(args: argparse.Namespace) -> int:
    """Phase 2: hash and inspect discovered files once with bounded workers."""
    roots = _import_scan_roots(args)
    if not roots:
        print("No folders to enrich.")
        return 0
    database_path = resolve_database_path(args.root, args.output)
    with closing(connect_sqlite_live(database_path)) as connection:
        init_sqlite(connection)
        candidates = [
            row[0]
            for row in connection.execute(
                """
                SELECT f.path
                FROM files f
                LEFT JOIN ingest_state state ON state.media_path=f.path
                WHERE state.enriched_at IS NULL
                ORDER BY f.path
                """
            )
            if _path_in_roots(row[0], roots) and Path(row[0]).is_file()
        ]
    total = len(candidates)
    print("STAGE:enrich", flush=True)
    print(f"PROGRESS:0/{total}", flush=True)
    failed = 0
    with closing(connect_sqlite_live(database_path)) as connection:
        init_sqlite(connection)
        with ThreadPoolExecutor(max_workers=max(1, min(8, args.workers))) as executor:
            futures = [executor.submit(_enrich_file, path) for path in candidates]
            for index, future in enumerate(as_completed(futures), 1):
                path_text, local_md5, width, height, error = future.result()
                now = datetime.now(timezone.utc).isoformat()
                if error:
                    failed += 1
                    connection.execute(
                        "UPDATE ingest_state SET phase='enrich', status='error', error=? WHERE media_path=?",
                        (error[:1000], path_text),
                    )
                else:
                    connection.execute("UPDATE files SET local_md5=? WHERE path=?", (local_md5, path_text))
                    connection.execute(
                        "UPDATE posts SET width=?, height=? WHERE file_id=(SELECT id FROM files WHERE path=?)",
                        (width, height, path_text),
                    )
                    connection.execute(
                        """
                        UPDATE ingest_state
                           SET phase='enriched', status='done', error=NULL, enriched_at=?
                         WHERE media_path=?
                        """,
                        (now, path_text),
                    )
                if index % 250 == 0:
                    connection.commit()
                if index % 50 == 0 or index == total:
                    print(f"PROGRESS:{index}/{total}", flush=True)
            connection.commit()
    print(f"Enriched {total - failed} media files; {failed} failed.")
    # A damaged file is recorded as resumable per-item state. It must not stop
    # an all-phases import from finalizing every healthy file.
    return 0


def run_import_finalize(args: argparse.Namespace) -> int:
    """Phase 4: reuse incremental sync, then mark the resumable phase ledger."""
    result = run_sync(args)
    if result:
        return result
    roots = _import_scan_roots(args)
    database_path = resolve_database_path(args.root, args.output)
    sidecar_dir = resolve_sidecar_dir(args)
    now = datetime.now(timezone.utc).isoformat()
    with closing(connect_sqlite_live(database_path)) as connection:
        for row in connection.execute("SELECT media_path FROM ingest_state"):
            if not _path_in_roots(row[0], roots):
                continue
            media_path = Path(row[0])
            has_sidecar = existing_metadata_path_for(media_path, ".danbooru.json", args.root, sidecar_dir) is not None
            connection.execute(
                """
                UPDATE ingest_state
                   SET phase=CASE WHEN status IN ('error', 'no_match') THEN phase ELSE 'finalized' END,
                       status=CASE WHEN status IN ('error', 'no_match') THEN status ELSE 'done' END,
                       error=CASE WHEN status IN ('error', 'no_match') THEN error ELSE NULL END,
                       metadata_at=CASE WHEN ? THEN COALESCE(metadata_at, ?) ELSE metadata_at END,
                       finalized_at=?
                 WHERE media_path=?
                """,
                (1 if has_sidecar else 0, now, now, row[0]),
            )
        connection.commit()
    return 0


def run_sync(args: argparse.Namespace) -> int:
    started = time.time()
    sidecar_dir = resolve_sidecar_dir(args)
    root = args.root.resolve()
    raw_paths = [
        path.expanduser().resolve(strict=False)
        for path in (args.paths or default_backfill_paths(root))
    ]
    scan_roots: list[Path] = []
    seen_roots: set[str] = set()
    for path in raw_paths:
        key = os.path.normcase(str(path))
        if key in seen_roots:
            continue
        seen_roots.add(key)
        if path.is_dir():
            scan_roots.append(path)
        else:
            print(f"Skipping missing folder: {path}", file=sys.stderr)
    if not scan_roots:
        print("No folders to sync.")
        return 0

    extra_roots: dict[str, str] = {}
    for scan_root in scan_roots:
        try:
            scan_root.relative_to(root)
        except ValueError:
            extra_roots[str(scan_root)] = scan_root.name

    # 1. Inventory media and sidecars \u2014 stat-only walk, no file contents read.
    media: dict[str, tuple[int, int]] = {}
    media_paths: dict[str, str] = {}
    sidecar_index: dict[str, tuple[str, int, int]] = {}

    def add_sidecars(found: dict[str, tuple[int, int]]) -> None:
        for path_text, stat_info in found.items():
            sidecar_index[os.path.normcase(path_text)] = (path_text, *stat_info)

    for scan_root in scan_roots:
        found_media, adjacent = scan_media_tree(scan_root, args.json_suffix)
        for path_text, stat_info in found_media.items():
            key = os.path.normcase(path_text)
            media[key] = stat_info
            media_paths[key] = path_text
        add_sidecars(adjacent)
        try:
            relative_root = scan_root.relative_to(root)
        except ValueError:
            continue
        central_tree = sidecar_dir / relative_root
        if central_tree.is_dir():
            _, central = scan_media_tree(central_tree, args.json_suffix, skip_special_dirs=False)
            add_sidecars(central)
    if extra_roots:
        outside_tree = sidecar_dir / "_outside_root"
        if outside_tree.is_dir():
            _, outside = scan_media_tree(outside_tree, args.json_suffix, skip_special_dirs=False)
            add_sidecars(outside)
    roots_tree = sidecar_dir / "roots"
    if roots_tree.is_dir():
        _, rooted = scan_media_tree(roots_tree, args.json_suffix, skip_special_dirs=False)
        add_sidecars(rooted)

    def sidecar_for(media_path_text: str) -> tuple[str, int, int] | None:
        media_path = Path(media_path_text)
        try:
            relative_media = media_path.relative_to(root)
            central = sidecar_dir / relative_media.parent / (media_path.name + args.json_suffix)
        except ValueError:
            digest = hashlib.sha256(media_path_text.encode("utf-8")).hexdigest()[:16]
            central = sidecar_dir / "_outside_root" / digest / (media_path.name + args.json_suffix)
        for candidate in (str(central), media_path_text + args.json_suffix):
            entry = sidecar_index.get(os.path.normcase(candidate))
            if entry:
                return entry
        # Digest fallback for externally-registered files whose sidecar was
        # written from a differently-cased/resolved path.
        resolved_candidate = metadata_path_for(media_path, args.json_suffix, root, sidecar_dir)
        return sidecar_index.get(os.path.normcase(str(resolved_candidate)))

    # 2. Load manifest and current rows, scoped to the scanned roots.
    prefixes = [os.path.normcase(str(scan_root)) + os.sep for scan_root in scan_roots]

    def in_scope(path_text: str) -> bool:
        key = os.path.normcase(path_text)
        return any(key.startswith(prefix) for prefix in prefixes)

    database_path = resolve_database_path(root, args.output)
    failed = 0
    imported_full = 0
    imported_minimal = 0
    removed = 0

    with closing(connect_sqlite_live(database_path)) as connection:
        init_sqlite(connection)

        manifest: dict[str, tuple[str, str | None, int | None, int | None, int | None, int | None]] = {}
        for row in connection.execute(
            """SELECT media_path, sidecar_path, sidecar_mtime, sidecar_size,
                      media_mtime, media_size
               FROM sync_manifest"""
        ):
            if in_scope(row[0]):
                manifest[os.path.normcase(row[0])] = (row[0], row[1], row[2], row[3], row[4], row[5])

        db_files: dict[str, tuple[int, str]] = {}
        for row in connection.execute("SELECT id, path FROM files"):
            if in_scope(row[1]):
                db_files[os.path.normcase(row[1])] = (row[0], row[1])

        # 3. Delta: what needs a full import, a minimal import, or removal.
        to_import_full: list[tuple[str, str]] = []
        to_import_minimal: list[str] = []
        for key, (media_mtime, media_size) in media.items():
            media_path_text = media_paths[key]
            entry = manifest.get(key)
            sidecar_entry = sidecar_for(media_path_text)
            if sidecar_entry:
                sidecar_path_text, sidecar_mtime, sidecar_size = sidecar_entry
                unchanged = (
                    entry is not None
                    and key in db_files
                    and entry[1] is not None
                    and os.path.normcase(entry[1]) == os.path.normcase(sidecar_path_text)
                    and entry[2] == sidecar_mtime
                    and entry[3] == sidecar_size
                )
                if not unchanged:
                    to_import_full.append((media_path_text, sidecar_path_text))
            else:
                unchanged = (
                    entry is not None
                    and key in db_files
                    and entry[1] is None
                    and entry[4] == media_mtime
                    and entry[5] == media_size
                )
                if not unchanged:
                    to_import_minimal.append(media_path_text)

        stale_keys = (set(manifest) | set(db_files)) - set(media)
        stale_paths: list[str] = []
        for key in stale_keys:
            if key in db_files:
                stale_paths.append(db_files[key][1])
            elif key in manifest:
                stale_paths.append(manifest[key][0])

        total = len(to_import_full) + len(to_import_minimal) + len(stale_paths)
        processed = 0
        print(f"PROGRESS:0/{total}", flush=True)

        def bump() -> None:
            nonlocal processed
            processed += 1
            if processed % 50 == 0 or processed == total:
                print(f"PROGRESS:{processed}/{total}", flush=True)

        tag_cache: dict[str, tuple[int, str]] = {}
        for media_path_text, sidecar_path_text in to_import_full:
            key = os.path.normcase(media_path_text)
            media_mtime, media_size = media[key]
            try:
                payload = json.loads(Path(sidecar_path_text).read_text(encoding="utf-8"))
                local_file = payload.get("local_file")
                if not isinstance(local_file, dict):
                    local_file = {}
                    payload["local_file"] = local_file
                local_file["path"] = media_path_text
                local_file["name"] = Path(media_path_text).name
                local_file["size"] = media_size
                import_payload_to_sqlite(
                    connection,
                    payload,
                    root,
                    tag_cache,
                    store_raw_json=not args.no_raw_json,
                    extra_roots=extra_roots,
                )
                sidecar_entry = sidecar_index[os.path.normcase(sidecar_path_text)]
                upsert_manifest_row(
                    connection,
                    media_path_text,
                    sidecar_entry[0],
                    sidecar_entry[1],
                    sidecar_entry[2],
                    media_mtime,
                    media_size,
                )
            except (OSError, json.JSONDecodeError, ValueError, sqlite3.Error) as exc:
                failed += 1
                print(f"Failed to import {sidecar_path_text}: {exc}", file=sys.stderr)
            else:
                imported_full += 1
                if imported_full % 500 == 0:
                    connection.commit()
            bump()

        for media_path_text in to_import_minimal:
            key = os.path.normcase(media_path_text)
            media_mtime, media_size = media[key]
            media_path = Path(media_path_text)
            try:
                folder = folder_for_media(media_path, root, extra_roots)
                import_minimal_media(connection, media_path, folder, media_size, root)
                upsert_manifest_row(
                    connection, media_path_text, None, None, None, media_mtime, media_size
                )
            except (OSError, sqlite3.Error) as exc:
                failed += 1
                print(f"Failed to index {media_path_text}: {exc}", file=sys.stderr)
            else:
                imported_minimal += 1
                if imported_minimal % 500 == 0:
                    connection.commit()
            bump()

        for start in range(0, len(stale_paths), 400):
            chunk = stale_paths[start:start + 400]
            placeholders = ",".join("?" for _ in chunk)
            connection.execute(
                f"""DELETE FROM post_tags WHERE post_id IN (
                        SELECT id FROM posts WHERE file_id IN (
                            SELECT id FROM files WHERE path IN ({placeholders})))""",
                chunk,
            )
            connection.execute(
                f"""DELETE FROM posts WHERE file_id IN (
                        SELECT id FROM files WHERE path IN ({placeholders}))""",
                chunk,
            )
            connection.execute(
                f"DELETE FROM files WHERE path IN ({placeholders})", chunk
            )
            connection.execute(
                f"DELETE FROM sync_manifest WHERE media_path IN ({placeholders})", chunk
            )
            removed += len(chunk)
            for _ in chunk:
                bump()
        if removed:
            connection.execute(
                "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM post_tags)"
            )

        connection.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ("last_synced_at", datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()

    unchanged = len(media) - imported_full - imported_minimal - failed
    elapsed = time.time() - started
    print(
        f"Sync complete in {elapsed:.1f}s: {imported_full} imported from sidecars, "
        f"{imported_minimal} indexed without sidecars, {unchanged} unchanged, "
        f"{removed} removed, {failed} failed"
    )
    return 1 if failed else 0


DIMENSION_TOKEN_RE = re.compile(r"(\d+)\s*[xX\u00d7]\s*(\d+)")
DIMENSION_FILTER_PREFIXES = {"res", "resolution", "dim", "dims", "dimension", "dimensions", "size"}


def normalize_dimension_tokens(raw: str) -> str:
    return DIMENSION_TOKEN_RE.sub(r"\1x\2", raw)


def add_dimension_search_filter(filters: dict[str, list[str] | str], value: str) -> bool:
    match = re.fullmatch(r"(>=|<=|>|<|=)?(\d+)x(\d+)", normalize_dimension_tokens(value).strip())
    if not match:
        return False

    operator = match.group(1) or "="
    filters.setdefault("width", [])
    assert isinstance(filters["width"], list)
    filters["width"].append(f"{operator}{match.group(2)}")
    filters.setdefault("height", [])
    assert isinstance(filters["height"], list)
    filters["height"].append(f"{operator}{match.group(3)}")
    return True


def parse_search_terms(terms: list[str]) -> tuple[list[tuple[str | None, str]], list[tuple[str | None, str]], dict[str, list[str] | str]]:
    include_tags: list[tuple[str | None, str]] = []
    exclude_tags: list[tuple[str | None, str]] = []
    filters: dict[str, list[str] | str] = {}
    categories = {"artist", "character", "copyright", "general", "meta", "unknown"}
    numeric_filters = {"width", "w", "height", "h", "pixels", "mp", "ratio", "score"}

    for raw_term in normalize_dimension_tokens(" ".join(terms)).split():
        term = raw_term.strip().strip("\"'")
        if not term:
            continue
        negate = term.startswith("-")
        if negate:
            term = term[1:]
        lowered = term.lower()
        if add_dimension_search_filter(filters, term):
            continue
        if ":" in term:
            prefix, value = term.split(":", 1)
            prefix = prefix.lower()
            if prefix == "rating":
                filters["rating"] = value
                continue
            if prefix == "ext":
                filters["ext"] = value.lower().lstrip(".")
                continue
            if prefix == "folder":
                filters["folder"] = value
                continue
            if prefix == "orientation":
                filters["orientation"] = value.lower()
                continue
            if prefix in DIMENSION_FILTER_PREFIXES and add_dimension_search_filter(filters, value):
                continue
            if prefix in numeric_filters:
                filters.setdefault(prefix, [])
                assert isinstance(filters[prefix], list)
                filters[prefix].append(value)
                continue
            if prefix in categories:
                target = exclude_tags if negate else include_tags
                target.append((prefix, value.lower()))
                continue
        target = exclude_tags if negate else include_tags
        target.append((None, lowered))

    return include_tags, exclude_tags, filters


def add_numeric_filter(
    where: list[str],
    params: list[Any],
    expr: str,
    values: list[str],
) -> None:
    for raw in values:
        match = re.fullmatch(
            r"\s*(>=|<=|>|<|=)?\s*(\d+(?:\.\d+)?)\s*",
            str(raw).strip("\"'"),
        )
        if not match:
            continue
        operator = match.group(1) or ">="
        where.append(f"{expr} {operator} ?")
        params.append(float(match.group(2)))


def add_dimension_filter(
    where: list[str],
    params: list[Any],
    filters: dict[str, list[str] | str],
) -> None:
    width_values = filters.get("width") or filters.get("w") or []
    height_values = filters.get("height") or filters.get("h") or []
    pixel_values = filters.get("pixels") or filters.get("mp") or []
    ratio_values = filters.get("ratio") or []
    if isinstance(width_values, list):
        add_numeric_filter(where, params, "p.width", width_values)
    if isinstance(height_values, list):
        add_numeric_filter(where, params, "p.height", height_values)
    if isinstance(pixel_values, list):
        add_numeric_filter(where, params, "(p.width * p.height)", pixel_values)
    if isinstance(ratio_values, list):
        add_numeric_filter(
            where, params, "(CAST(p.width AS REAL) / NULLIF(p.height, 0))", ratio_values
        )
    orientation = filters.get("orientation")
    if orientation in ("portrait", "vertical"):
        where.append("p.height > p.width")
    elif orientation in ("landscape", "horizontal", "wide"):
        where.append("p.width > p.height")
    elif orientation == "square":
        where.append("p.width = p.height")


def add_tag_condition(
    where: list[str],
    params: list[Any],
    tag: tuple[str | None, str],
    negate: bool = False,
) -> None:
    category, name = tag
    clause = [
        "SELECT 1 FROM post_tags pt",
        "JOIN tags t ON t.id = pt.tag_id",
        "WHERE pt.post_id = p.id AND t.name = ?",
    ]
    params.append(name)
    if category:
        clause.append("AND t.category = ?")
        params.append(category)
    exists = "EXISTS (" + " ".join(clause) + ")"
    where.append(f"NOT {exists}" if negate else exists)


def run_search(args: argparse.Namespace) -> int:
    database_path = resolve_database_path(args.root, args.database)
    if not database_path.exists():
        print(f"Database not found: {database_path}. Run the sqlite command first.", file=sys.stderr)
        return 1
    include_tags, exclude_tags, filters = parse_search_terms(args.terms)
    where: list[str] = []
    params: list[Any] = []
    for tag in include_tags:
        add_tag_condition(where, params, tag)
    for tag in exclude_tags:
        add_tag_condition(where, params, tag, negate=True)
    if rating := filters.get("rating"):
        where.append("p.rating = ?")
        params.append(str(rating)[:1].lower())
    if ext := filters.get("ext"):
        where.append("f.ext = ?")
        params.append(ext)
    if folder := filters.get("folder"):
        where.append("f.folder LIKE ?")
        params.append(f"%{folder}%")
    add_dimension_filter(where, params, filters)
    add_numeric_filter(where, params, "p.score", list(filters.get("score") or []))
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT
            f.path,
            p.danbooru_post_id,
            p.rating,
            p.score,
            p.width,
            p.height,
            group_concat(t.name, ' ') AS tags
        FROM posts p
        JOIN files f ON f.id = p.file_id
        LEFT JOIN post_tags pt ON pt.post_id = p.id
        LEFT JOIN tags t ON t.id = pt.tag_id
        {where_sql}
        GROUP BY p.id
        ORDER BY COALESCE(p.score, -999999) DESC, f.path ASC
        LIMIT ?
    """
    params.append(args.limit)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(sql, params).fetchall()

    if args.json:
        records = [dict(row) for row in rows]
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return 0

    print(f"Found {len(rows)} result(s)")
    for row in rows:
        print(
            f"{row['path']} | post:{row['danbooru_post_id']} "
            f"rating:{row['rating']} score:{row['score']} "
            f"{row['width']}x{row['height']}"
        )
    return 0


def path_arg(value: str) -> Path:
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download Danbooru files with gallery-dl sidecars, or backfill "
            "metadata for existing local media by Danbooru MD5 lookup."
        )
    )
    parser.add_argument(
        "--root",
        type=path_arg,
        default=project_root(),
        help="Workspace root. Default: project root.",
    )
    parser.add_argument(
        "--gallery-dl-dir",
        type=path_arg,
        default=project_root() / "_gallery-dl",
        help="gallery-dl config/archive work folder. Relative paths use the project root.",
    )
    parser.add_argument(
        "--sidecar-dir",
        type=path_arg,
        default=project_root() / "data" / "sidecars",
        help="Central sidecar folder. Relative paths use the project root.",
    )
    parser.add_argument(
        "--user-db",
        type=path_arg,
        default=project_root() / "data" / "user.sqlite",
        help="User database containing stable registered-root identities.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser(
        "download",
        help="Use gallery-dl to download a Danbooru tag search with JSON and tag sidecars.",
    )
    download.add_argument("tags", nargs="+", help="Danbooru tag query, e.g. 1girl rating:safe")
    download.add_argument("--folder", default="Danbooru", help="Top-level output folder.")
    download.add_argument("--tag-folder", help="Output subfolder. Default: sanitized tag query.")
    download.add_argument("--destination", type=path_arg, help="Exact output directory (used by the in-app downloader).")
    download.add_argument("--filename", default="{id}_{md5}.{extension}", help="gallery-dl filename format.")
    download.add_argument("--limit", type=int, help="Limit downloads with gallery-dl --range 1-N.")
    download.add_argument("--archive", type=path_arg, help="gallery-dl archive sqlite path.")
    download.add_argument("--sleep-request", default="1.0-2.0", help="gallery-dl request delay.")
    download.add_argument("--sleep-429", default="60-120", help="gallery-dl 429 retry delay.")
    download.add_argument("--retries", type=int, default=5)
    download.add_argument("--metadata-includes", help="Comma-separated Danbooru extra metadata includes.")
    download.add_argument("--username", help="Danbooru username, or set DANBOORU_USERNAME.")
    download.add_argument("--api-key", help="Danbooru API key, or set DANBOORU_API_KEY.")
    download.add_argument("--ugoira-zip", action="store_true", help="Download ugoira ZIPs instead of converted videos.")
    download.add_argument("--external", action="store_true", help="Follow source URLs for restricted/unavailable posts.")
    download.add_argument("--dry-run", action="store_true", help="Print config and command without running gallery-dl.")
    download.set_defaults(json_suffix=".danbooru.json", tags_suffix=".tags.txt")
    download.set_defaults(func=run_download)

    backfill = subparsers.add_parser(
        "backfill",
        help="Write sidecar tags/metadata for existing local media by querying Danbooru.",
    )
    backfill.add_argument("paths", nargs="*", type=path_arg, help="Files/folders to scan. Defaults to Danbooru folders.")
    backfill.add_argument("--limit", type=int, help="Only process the first N media files.")
    backfill.add_argument("--delay", type=float, default=1.0, help="Seconds to wait between Danbooru API requests.")
    backfill.add_argument("--retries", type=int, default=3)
    backfill.add_argument("--json-suffix", default=".danbooru.json")
    backfill.add_argument("--tags-suffix", default=".tags.txt")
    backfill.add_argument("--overwrite", action="store_true", help="Rewrite existing sidecars.")
    backfill.add_argument(
        "--archive-replaced-sidecars",
        action="store_true",
        help="Copy existing sidecars to the sidecar archive before overwriting them.",
    )
    backfill.add_argument(
        "--sidecar-archive-dir",
        type=path_arg,
        help="Archive folder for replaced sidecars. Default: project data/sidecar_archive/<timestamp>.",
    )
    backfill.add_argument(
        "--filename-md5-only",
        action="store_true",
        help="Only inspect files with a 32-character hex hash in the filename.",
    )
    backfill.add_argument(
        "--gallery-dl-names-only",
        action="store_true",
        help="Only inspect gallery-dl-style filenames beginning with double underscores.",
    )
    backfill.add_argument(
        "--index-jsonl",
        type=path_arg,
        help="Also write matched metadata to one newline-delimited JSON index file.",
    )
    backfill.add_argument(
        "--append-index",
        action="store_true",
        help="Append to --index-jsonl instead of replacing it at the start of the run.",
    )
    backfill.add_argument("--extra-metadata", action="store_true", help="Fetch notes/commentary/parent/children/uploader.")
    backfill.add_argument("--metadata-includes", help="Comma-separated Danbooru extra metadata includes.")
    backfill.add_argument("--username", help="Danbooru username, or set DANBOORU_USERNAME.")
    backfill.add_argument("--api-key", help="Danbooru API key, or set DANBOORU_API_KEY.")
    backfill.add_argument("--dry-run", action="store_true", help="List files that would be inspected.")
    backfill.add_argument(
        "--use-indexed-md5",
        action="store_true",
        help="Reuse local_md5 from the SQLite index instead of hashing media again.",
    )
    backfill.add_argument(
        "--database",
        type=path_arg,
        default=Path("data") / "danbooru.sqlite",
        help="SQLite index used by --use-indexed-md5.",
    )
    backfill.set_defaults(func=run_backfill)

    import_discover = subparsers.add_parser(
        "import-discover",
        help="Import phase 1: discover paths using directory metadata only.",
    )
    import_discover.add_argument("paths", nargs="*", type=path_arg)
    import_discover.add_argument("--output", type=path_arg, default=Path("data") / "danbooru.sqlite")
    import_discover.set_defaults(func=run_import_discover)

    import_enrich = subparsers.add_parser(
        "import-enrich",
        help="Import phase 2: hash files and read dimensions with bounded workers.",
    )
    import_enrich.add_argument("paths", nargs="*", type=path_arg)
    import_enrich.add_argument("--output", type=path_arg, default=Path("data") / "danbooru.sqlite")
    import_enrich.add_argument("--workers", type=int, default=3)
    import_enrich.set_defaults(func=run_import_enrich)

    index = subparsers.add_parser(
        "index",
        help="Build one central JSON search index from existing .danbooru.json sidecars.",
    )
    index.add_argument("paths", nargs="*", type=path_arg, help="Folders to scan. Defaults to Danbooru folders.")
    index.add_argument(
        "--output",
        type=path_arg,
        default=Path("data") / "danbooru-index.json",
        help="Central JSON index to write.",
    )
    index.add_argument("--json-suffix", default=".danbooru.json")
    index.add_argument("--limit", type=int, help="Only index the first N sidecars.")
    index.add_argument("--pretty", action="store_true", help="Write indented JSON. Larger but easier to inspect.")
    index.add_argument("--full", action="store_true", help="Store full per-file payloads instead of compact records.")
    index.set_defaults(func=run_index)

    sqlite = subparsers.add_parser(
        "sqlite",
        help="Build a searchable SQLite database from existing .danbooru.json sidecars.",
    )
    sqlite.add_argument("paths", nargs="*", type=path_arg, help="Folders to scan. Defaults to Danbooru folders.")
    sqlite.add_argument(
        "--output",
        type=path_arg,
        default=Path("data") / "danbooru.sqlite",
        help="SQLite database to write.",
    )
    sqlite.add_argument("--json-suffix", default=".danbooru.json")
    sqlite.add_argument("--limit", type=int, help="Only import the first N sidecars.")
    sqlite.add_argument("--replace", action="store_true", help="Delete and rebuild the database before importing.")
    sqlite.add_argument(
        "--commit-every",
        type=int,
        default=5000,
        help="Commit after every N imported sidecars. Use 0 to commit once at the end.",
    )
    sqlite.add_argument(
        "--include-missing-media",
        dest="skip_missing_media",
        action="store_false",
        help="Import sidecars even when their referenced media file is missing.",
    )
    sqlite.add_argument(
        "--no-raw-json",
        action="store_true",
        help="Do not store the full sidecar payload in the raw_json column.",
    )
    sqlite.add_argument(
        "--extra-root",
        action="append",
        type=path_arg,
        default=[],
        help="Registered external media folder; its files get the folder's name as their folder label. Repeatable.",
    )
    sqlite.set_defaults(skip_missing_media=True)
    sqlite.set_defaults(func=run_sqlite)

    sync = subparsers.add_parser(
        "sync",
        help="Incrementally sync media folders into the SQLite database: import new/changed sidecars, index sidecar-less media, remove rows for deleted files. No rebuild.",
    )
    sync.add_argument("paths", nargs="*", type=path_arg, help="Media folders to sync. Defaults to Danbooru folders.")
    sync.add_argument(
        "--output",
        type=path_arg,
        default=Path("data") / "danbooru.sqlite",
        help="SQLite database to update.",
    )
    sync.add_argument("--json-suffix", default=".danbooru.json")
    sync.add_argument(
        "--no-raw-json",
        action="store_true",
        help="Do not store the full sidecar payload in the raw_json column.",
    )
    sync.set_defaults(func=run_sync)

    import_finalize = subparsers.add_parser(
        "import-finalize",
        help="Import phase 4: incrementally sync sidecars and finalize the import ledger.",
    )
    import_finalize.add_argument("paths", nargs="*", type=path_arg)
    import_finalize.add_argument("--output", type=path_arg, default=Path("data") / "danbooru.sqlite")
    import_finalize.add_argument("--json-suffix", default=".danbooru.json")
    import_finalize.add_argument("--no-raw-json", action="store_true")
    import_finalize.set_defaults(func=run_import_finalize)

    clean_sidecars = subparsers.add_parser(
        "clean-sidecars",
        help="Delete .danbooru.json and .tags.txt sidecars whose original media file is missing.",
    )
    clean_sidecars.add_argument("paths", nargs="*", type=path_arg, help="Folders to scan. Defaults to Danbooru folders.")
    clean_sidecars.add_argument("--json-suffix", default=".danbooru.json")
    clean_sidecars.add_argument("--tags-suffix", default=".tags.txt")
    clean_sidecars.add_argument("--limit", type=int, help="Only inspect/delete the first N orphan sidecars.")
    clean_sidecars.add_argument("--dry-run", action="store_true", help="Print sidecars that would be deleted without deleting them.")
    clean_sidecars.set_defaults(func=run_clean_sidecars)

    search = subparsers.add_parser(
        "search",
        help="Search the SQLite database by Danbooru tags and simple filters.",
    )
    search.add_argument(
        "--database",
        type=path_arg,
        default=Path("data") / "danbooru.sqlite",
        help="SQLite database to search.",
    )
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--json", action="store_true", help="Print search results as JSON.")
    search.add_argument(
        "terms",
        nargs=argparse.REMAINDER,
        help=(
            "Tags/filters. Examples: 2b_(nier:automata) solo rating:s ext:jpg "
            "artist:atomicmrshmallw -chibi 2160x3840 dim:>=1920x1080 orientation:portrait"
        ),
    )
    search.set_defaults(func=run_search)

    return parser


def main() -> int:
    global _LIBRARY_ROOTS
    parser = build_parser()
    args = parser.parse_args()
    args.root = args.root.resolve()
    _LIBRARY_ROOTS = load_library_roots(args.user_db.resolve(strict=False))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
