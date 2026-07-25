"""Read-only inspection of archive contents for the Files base (V1.1.2).

A hoard is full of zips — models, subtitle packs, comic archives — and opening
one just to remember what is inside means extracting it somewhere. This lists
the contents without unpacking anything.

Safety, because an archive is attacker-shaped data even when the user put it
there themselves:

- **Only the central directory is read.** ``ZipFile.infolist()`` returns stored
  metadata; nothing is ever decompressed, so a zip bomb has nothing to expand.
  ``read()``/``extract()`` are deliberately never called anywhere in this module.
- **Entry names are display strings only.** They are never joined to a path,
  never used to open anything, and are returned exactly as stored — so a crafted
  ``../../`` name is inert text on screen rather than a traversal.
- **The entry count is capped.** A zip may declare millions of members; the
  listing stops at a bound and reports that it was truncated.
- **Content decides, not the extension.** ``zipfile.is_zipfile`` inspects the
  file itself, so a mislabelled ``.zip`` that is not one is refused rather than
  half-parsed.

Isolated: no Danbooru or ``core`` imports.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path


# A personal archive rarely exceeds a few thousand members; past this the
# listing is unreadable anyway and the cap is what protects the response.
MAX_ENTRIES = 2000


class ArchiveUnreadable(Exception):
    """The file is not a readable archive; carries an HTTP-ready reason."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ArchiveEntry:
    name: str
    size: int
    compressed_size: int
    is_dir: bool


@dataclass(frozen=True)
class ArchiveListing:
    entries: list[ArchiveEntry]
    total_entries: int
    truncated: bool
    total_size: int
    compressed_size: int


def is_archive(path: Path) -> bool:
    """Whether this file is really a zip container, judged by content."""
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def list_archive(path: Path, limit: int = MAX_ENTRIES) -> ArchiveListing:
    """List an archive's members without extracting or decompressing any of them.

    Totals cover every member, not just the ones returned, so a truncated
    listing still reports the archive's true size.
    """
    if not is_archive(path):
        raise ArchiveUnreadable(415, "That file is not a readable archive")

    try:
        with zipfile.ZipFile(path) as archive:
            # Parsed from the central directory at open time; no member is read.
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise ArchiveUnreadable(400, f"The archive could not be read: {exc}") from exc

    total_size = sum(info.file_size for info in infos)
    compressed = sum(info.compress_size for info in infos)
    entries = [
        ArchiveEntry(
            name=info.filename,
            size=info.file_size,
            compressed_size=info.compress_size,
            is_dir=info.is_dir(),
        )
        for info in infos[:limit]
    ]
    return ArchiveListing(
        entries=entries,
        total_entries=len(infos),
        truncated=len(infos) > limit,
        total_size=total_size,
        compressed_size=compressed,
    )
