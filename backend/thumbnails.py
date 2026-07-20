from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from PIL import Image, ImageOps

from config import THUMB_DIR, get_thumbnail_cache_limit_bytes
DEFAULT_THUMB_SIZE = 300
THUMBNAIL_TIERS = (300, 600, 1200)
THUMB_CACHE_VERSION = "v4"
WEBP_QUALITY = 88
SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".jfif"}
SUPPORTED_VIDEOS = {".mp4", ".webm"}

# These are local library files, not untrusted uploads. Some Danbooru images are
# very large source canvases, and the gallery still needs small previews for them.
Image.MAX_IMAGE_PIXELS = 500_000_000
_cache_lock = threading.Lock()
_key_locks: tuple[threading.Lock, ...] = tuple(threading.Lock() for _ in range(64))
_prune_state_lock = threading.Lock()
_writes_since_prune = 0
_prune_scheduled = False
_CURRENT_CACHE_RE = re.compile(r"^([0-9a-f]{32})_v4(?:_(600|1200))?\.webp$", re.IGNORECASE)
logger = logging.getLogger(__name__)


def normalize_thumbnail_size(size: int) -> int:
    for tier in THUMBNAIL_TIERS:
        if size <= tier:
            return tier
    return THUMBNAIL_TIERS[-1]


def _file_md5(source_path: str) -> str:
    digest = hashlib.md5()
    with Path(source_path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def thumbnail_cache_token(source_path: str, content_md5: str | None = None) -> str:
    """Cheap browser cache token; indexed MD5 wins, path is the fallback."""
    if content_md5 and len(content_md5) == 32:
        return content_md5.lower()
    return hashlib.md5(source_path.encode("utf-8")).hexdigest()


def _thumbnail_content_key(source_path: str, content_md5: str | None = None) -> str:
    if content_md5 and len(content_md5) == 32:
        return content_md5.lower()
    try:
        return _file_md5(source_path)
    except OSError:
        return hashlib.md5(source_path.encode("utf-8")).hexdigest()


def get_thumbnail_path(source_path: str, max_size: int = DEFAULT_THUMB_SIZE, content_md5: str | None = None) -> Path:
    max_size = normalize_thumbnail_size(max_size)
    suffix = "" if max_size == DEFAULT_THUMB_SIZE else f"_{max_size}"
    return THUMB_DIR / f"{_thumbnail_content_key(source_path, content_md5)}_{THUMB_CACHE_VERSION}{suffix}.webp"


def remove_legacy_thumbnail_cache(source_path: str, content_md5: str | None = None) -> int:
    if not THUMB_DIR.exists():
        return 0
    key = _thumbnail_content_key(source_path, content_md5)
    current_prefix = f"{key}_{THUMB_CACHE_VERSION}"
    removed = 0
    for thumb_path in THUMB_DIR.glob(f"{key}*.webp"):
        if thumb_path.name.startswith(current_prefix):
            continue
        try:
            thumb_path.unlink()
            removed += 1
        except OSError:
            pass
    legacy_path_key = hashlib.md5(source_path.encode("utf-8")).hexdigest()
    if legacy_path_key != key:
        for thumb_path in THUMB_DIR.glob(f"{legacy_path_key}_v*.webp"):
            try:
                thumb_path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _video_frame(source_path: Path) -> Image.Image:
    executable: str | None = None
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).resolve().parent / "ffmpeg.exe"
        if bundled.is_file():
            executable = str(bundled)
        else:
            raise RuntimeError(
                f"Portable video thumbnails require ffmpeg.exe beside Keivotos.exe: {bundled}"
            )
    executable = executable or shutil.which("ffmpeg")
    if executable is None:
        import imageio_ffmpeg

        executable = imageio_ffmpeg.get_ffmpeg_exe()

    command = [
        executable, "-hide_banner", "-loglevel", "error",
        "-ss", "0.1", "-i", str(source_path), "-frames:v", "1",
        "-f", "image2pipe", "-vcodec", "png", "-",
    ]
    result = subprocess.run(command, capture_output=True, timeout=30, check=True)
    if not result.stdout:
        raise RuntimeError("Video produced no thumbnail frame")
    image = Image.open(io.BytesIO(result.stdout))
    image.load()
    return image


def _thumbnail_lock(path: Path) -> threading.Lock:
    return _key_locks[hash(str(path)) % len(_key_locks)]


def _schedule_thumbnail_prune() -> None:
    global _prune_scheduled
    with _prune_state_lock:
        if _prune_scheduled:
            return
        _prune_scheduled = True

    def worker() -> None:
        global _prune_scheduled
        try:
            prune_thumbnail_cache(get_thumbnail_cache_limit_bytes())
        finally:
            with _prune_state_lock:
                _prune_scheduled = False

    threading.Thread(target=worker, name="thumbnail-cache-prune", daemon=True).start()


def ensure_thumbnail(
    source_path: str,
    max_size: int = DEFAULT_THUMB_SIZE,
    content_md5: str | None = None,
) -> Path | None:
    global _writes_since_prune
    max_size = normalize_thumbnail_size(max_size)
    src = Path(source_path)
    if not src.exists() or src.suffix.lower() not in SUPPORTED_IMAGES | SUPPORTED_VIDEOS:
        return None
    thumb_path = get_thumbnail_path(source_path, max_size, content_md5)

    if thumb_path.exists():
        remove_legacy_thumbnail_cache(source_path, content_md5)
        return thumb_path

    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    with _thumbnail_lock(thumb_path):
        if thumb_path.exists():
            return thumb_path
        remove_legacy_thumbnail_cache(source_path, content_md5)
        try:
            if src.suffix.lower() in SUPPORTED_VIDEOS:
                img = _video_frame(src)
            else:
                img = Image.open(src)
            with img:
                source_format = img.format
                try:
                    img.seek(0)
                except EOFError:
                    pass

                if source_format == "JPEG":
                    img.draft("RGB", (max_size, max_size))

                img = ImageOps.exif_transpose(img)
                img.thumbnail((max_size, max_size), Image.LANCZOS)
                if img.mode != "RGB":
                    img = img.convert("RGB")
            img.save(thumb_path, "WEBP", quality=WEBP_QUALITY, method=5)
            should_prune = False
            with _prune_state_lock:
                _writes_since_prune += 1
                if _writes_since_prune >= 25:
                    _writes_since_prune = 0
                    should_prune = True
            if should_prune:
                _schedule_thumbnail_prune()
            return thumb_path
        except Exception as exc:  # noqa: BLE001 - failed previews degrade to placeholders.
            logger.warning("Could not create thumbnail for %s: %s", src, exc)
            return None


def clear_thumbnail_cache() -> int:
    if not THUMB_DIR.exists():
        return 0
    count = sum(1 for _ in THUMB_DIR.glob("*.webp"))
    shutil.rmtree(THUMB_DIR, ignore_errors=True)
    return count


def thumbnail_cache_status() -> dict:
    count = size = legacy = 0
    tiers = {str(tier): 0 for tier in THUMBNAIL_TIERS}
    if THUMB_DIR.exists():
        for path in THUMB_DIR.glob("*.webp"):
            try:
                size += path.stat().st_size
                count += 1
            except OSError:
                continue
            match = _CURRENT_CACHE_RE.match(path.name)
            if not match:
                legacy += 1
            else:
                tiers[match.group(2) or "300"] += 1
    return {
        "files": count,
        "bytes": size,
        "legacy_files": legacy,
        "tiers": tiers,
        "limit_bytes": get_thumbnail_cache_limit_bytes(),
    }


def cleanup_thumbnail_cache(valid_keys: set[str]) -> dict:
    """Remove stale versions, noncanonical sizes, and thumbnails no longer indexed."""
    removed = removed_bytes = 0
    if not THUMB_DIR.exists():
        return {**thumbnail_cache_status(), "removed": 0, "removed_bytes": 0}
    normalized_keys = {key.lower() for key in valid_keys}
    with _cache_lock:
        for path in THUMB_DIR.glob("*.webp"):
            match = _CURRENT_CACHE_RE.match(path.name)
            if match and match.group(1).lower() in normalized_keys:
                continue
            try:
                size = path.stat().st_size
                path.unlink()
                removed += 1
                removed_bytes += size
            except OSError:
                continue
    return {**thumbnail_cache_status(), "removed": removed, "removed_bytes": removed_bytes}


def prune_thumbnail_cache(limit_bytes: int) -> dict:
    """Keep the derived cache below the configured limit by oldest mtime."""
    if not THUMB_DIR.exists():
        return {**thumbnail_cache_status(), "removed": 0, "removed_bytes": 0}
    entries: list[tuple[float, int, Path]] = []
    total = 0
    for path in THUMB_DIR.glob("*.webp"):
        try:
            stat = path.stat()
        except OSError:
            continue
        total += stat.st_size
        entries.append((stat.st_mtime, stat.st_size, path))
    removed = removed_bytes = 0
    if total > limit_bytes:
        with _cache_lock:
            for _, size, path in sorted(entries):
                if total <= limit_bytes:
                    break
                try:
                    path.unlink()
                except OSError:
                    continue
                total -= size
                removed += 1
                removed_bytes += size
    return {**thumbnail_cache_status(), "removed": removed, "removed_bytes": removed_bytes}
