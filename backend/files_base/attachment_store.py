"""Content-addressed byte store for annotation attachments (V1.1.1).

Per the user's decision, attachment bytes live **inside a registered Files
folder** (their own storage), not under the suite's AppData home — so a
screenshot of a since-deleted store page rides along with the archive it
documents and is captured by the user's ordinary disk backups.

Layout: ``<store_root>/.keivotos/attachments/<first-2-of-hash>/<hash><ext>``.
The ``.keivotos`` directory is excluded from the Files scan (see
``files_base.index``), so attachments never appear as browsable files. Each row
records its ``store_root`` so the bytes stay findable even if which folder is
"first" later changes.

Isolated: no Danbooru or ``core`` imports. Pillow is used only to read image
dimensions and never blocks a save if it fails.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path


ATTACHMENT_DIR_NAME = ".keivotos"
ATTACHMENT_SUBPATH = Path(ATTACHMENT_DIR_NAME) / "attachments"


def attachment_root(store_root: str | Path) -> Path:
    return Path(store_root) / ATTACHMENT_SUBPATH


def attachment_path(store_root: str | Path, content_hash: str, ext: str) -> Path:
    suffix = ("." + ext.lstrip(".").lower()) if ext else ""
    return attachment_root(store_root) / content_hash[:2] / f"{content_hash}{suffix}"


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def write_attachment(store_root: str | Path, content_hash: str, ext: str, data: bytes) -> Path:
    """Write bytes content-addressed; a no-op if the same content already exists."""
    path = attachment_path(store_root, content_hash, ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
    return path


def delete_attachment_file(store_root: str | Path, content_hash: str, ext: str) -> None:
    """Remove the stored bytes (used only after the last row referencing them goes)."""
    attachment_path(store_root, content_hash, ext).unlink(missing_ok=True)


def image_dimensions(data: bytes) -> tuple[int | None, int | None]:
    """Best-effort (width, height) for an image; ``(None, None)`` on any failure."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:  # noqa: BLE001 - dimensions are optional metadata.
        return None, None


def extension_for(file_name: str, media_type: str) -> str:
    """Pick a storage extension from the upload name, falling back to its type."""
    suffix = Path(file_name).suffix.lower().lstrip(".")
    if suffix:
        return suffix
    subtype = media_type.split("/", 1)[-1].strip().lower()
    return {"jpeg": "jpg", "quicktime": "mov", "x-matroska": "mkv"}.get(subtype, subtype)
