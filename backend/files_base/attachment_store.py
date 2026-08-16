"""Content-addressed byte store for annotation attachments (V1.1.1).

Per the user's decision, attachment bytes live **inside a registered Files
folder** (their own storage), not under the suite's AppData home — so a
screenshot of a since-deleted store page rides along with the archive it
documents and is captured by the user's ordinary disk backups.

Two layouts, chosen per write by the configured mode (see
``config.attachment_store_mode``):

* **managed** — ``<store_root>/.keivotos/attachments/<first-2-of-hash>/<hash><ext>``.
  ``.keivotos`` is excluded from the Files scan (see ``files_base.index``), so
  these never appear as browsable files.
* **folder** — ``<store_root>/Attachments/<hash><ext>``. A browsable subfolder, so
  the attachment shows up in Files alongside the media it documents.

Each row records only its ``store_root``; ``resolve_attachment`` finds the bytes
under whichever layout they were written in, so rows survive a later mode change.

Isolated: no Danbooru or ``core`` imports. Pillow is used only to read image
dimensions and never blocks a save if it fails.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path


ATTACHMENT_DIR_NAME = ".keivotos"
ATTACHMENT_SUBPATH = Path(ATTACHMENT_DIR_NAME) / "attachments"
# Folder-mode attachments live here instead — a browsable subfolder (not the
# scan-excluded ``.keivotos``) so they appear in Files. Content-hash names keep
# the store deduplicated; the flat layout keeps the folder easy to browse.
VISIBLE_DIR_NAME = "Attachments"


def attachment_root(store_root: str | Path) -> Path:
    return Path(store_root) / ATTACHMENT_SUBPATH


def _hashed_name(content_hash: str, ext: str) -> str:
    suffix = ("." + ext.lstrip(".").lower()) if ext else ""
    return f"{content_hash}{suffix}"


def attachment_path(
    store_root: str | Path, content_hash: str, ext: str, *, visible: bool = False
) -> Path:
    """Where an attachment's bytes sit for the given storage mode.

    ``visible`` selects folder mode (``<root>/Attachments/<hash>.<ext>``, flat and
    browsable); the default is managed mode (hidden, sharded under ``.keivotos``).
    """
    name = _hashed_name(content_hash, ext)
    if visible:
        return Path(store_root) / VISIBLE_DIR_NAME / name
    return attachment_root(store_root) / content_hash[:2] / name


def resolve_attachment(store_root: str | Path, content_hash: str, ext: str) -> Path:
    """The bytes' real location, tolerant of either layout.

    A row records only its ``store_root``; the same root+hash maps to exactly one
    physical file, so preferring the visible path when it exists and otherwise the
    managed path resolves rows written in either mode (and legacy rows).
    """
    visible = attachment_path(store_root, content_hash, ext, visible=True)
    if visible.exists():
        return visible
    return attachment_path(store_root, content_hash, ext, visible=False)


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def write_attachment(
    store_root: str | Path, content_hash: str, ext: str, data: bytes, *, visible: bool = False
) -> Path:
    """Write bytes content-addressed; a no-op if the same content already exists."""
    path = attachment_path(store_root, content_hash, ext, visible=visible)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
    return path


def delete_attachment_file(store_root: str | Path, content_hash: str, ext: str) -> None:
    """Remove the stored bytes (used only after the last row referencing them goes).

    Clears both layouts so a mode change between write and delete cannot orphan the
    file; only one of them exists for a given root, so this removes exactly it.
    """
    for visible in (True, False):
        attachment_path(store_root, content_hash, ext, visible=visible).unlink(missing_ok=True)


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
