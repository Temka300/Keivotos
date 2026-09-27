"""Bounded, local Markdown operations; no rendering or network access."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
from pathlib import Path

from files_base import index, serving, sources

MAX_BYTES = 1024 * 1024
MAX_FILES = 2000
_writes = threading.RLock()
_reserved = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.IGNORECASE)
_session = re.compile(r"^[a-f0-9]{32}$")


class DocumentError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def valid_name(name: str) -> str:
    if (not name or len(name) > 128 or name != name.strip() or name.endswith((".", " "))
            or name in {".", ".."} or "/" in name or "\\" in name or ":" in name
            or any(ord(char) < 32 for char in name) or _reserved.match(name)
            or Path(name).suffix.lower() != ".md" or not name[:-3].strip()):
        raise DocumentError(400, "Choose a valid Markdown filename ending in .md")
    return name


def _root(source: sources.Source, suite_home: Path) -> Path:
    try:
        root = serving.resolve_within_source(source.path, "", [suite_home])
    except serving.ServeDenied as error:
        raise DocumentError(error.status_code, "Language folder is unavailable") from error
    if not root.is_dir():
        raise DocumentError(404, "Language folder is unavailable")
    return root


def _existing(root: Path, name: str, suite_home: Path) -> Path:
    valid_name(name)
    candidate = root / name
    if candidate.is_symlink():
        raise DocumentError(403, "Linked Markdown files cannot be edited")
    try:
        path = serving.resolve_served_file(root, name, [suite_home])
    except serving.ServeDenied as error:
        raise DocumentError(error.status_code, "Markdown file is unavailable") from error
    if path.suffix.lower() != ".md":
        raise DocumentError(400, "Only Markdown files can be edited")
    return path


def _bytes(path: Path) -> bytes:
    try:
        if path.stat().st_size > MAX_BYTES:
            raise DocumentError(413, "Markdown file is too large to edit")
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    except OSError as error:
        raise DocumentError(422, "Markdown file could not be read") from error
    if len(data) > MAX_BYTES:
        raise DocumentError(413, "Markdown file is too large to edit")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DocumentError(422, "Markdown file is not UTF-8") from error
    return data


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def list_documents(source: sources.Source, suite_home: Path) -> list[dict]:
    root = _root(source, suite_home)
    result = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.name.lower().endswith(".md") and entry.is_file(follow_symlinks=False):
                    if len(result) >= MAX_FILES:
                        raise DocumentError(413, "Too many Markdown files in this folder")
                    result.append({"name": entry.name, "size": entry.stat(follow_symlinks=False).st_size})
    except OSError as error:
        raise DocumentError(422, "Language folder could not be listed") from error
    return sorted(result, key=lambda item: item["name"].casefold())


def read_document(source: sources.Source, suite_home: Path, name: str) -> dict:
    root = _root(source, suite_home)
    data = _bytes(_existing(root, name, suite_home))
    return {"name": name, "content": data.decode("utf-8"), "revision": _revision(data)}


def create_document(source: sources.Source, suite_home: Path) -> dict:
    root = _root(source, suite_home)
    with _writes:
        for number in range(1, MAX_FILES + 2):
            name = "New File.md" if number == 1 else f"New File ({number}).md"
            try:
                with (root / name).open("x", encoding="utf-8"):
                    pass
            except FileExistsError:
                continue
            except OSError as error:
                raise DocumentError(422, "Markdown file could not be created") from error
            return {"name": name, "content": "", "revision": _revision(b"")}
    raise DocumentError(409, "No available New File name remains")


def rename_document(source: sources.Source, suite_home: Path, name: str,
                    new_name: str, revision: str) -> dict:
    root = _root(source, suite_home)
    valid_name(new_name)
    with _writes:
        old = _existing(root, name, suite_home)
        data = _bytes(old)
        if _revision(data) != revision:
            raise DocumentError(409, "Markdown file changed outside Keivotos; reopen it before renaming")
        if name == new_name:
            return {"name": name, "content": data.decode("utf-8"), "revision": revision}
        target = root / new_name
        if target.exists() or target.is_symlink():
            if os.name != "nt" or not old.samefile(target) or name.casefold() != new_name.casefold():
                raise DocumentError(409, "A Markdown file with that name already exists")
        try:
            if os.name == "nt":
                old.rename(target)
            else:
                os.link(old, target)
                old.unlink()
        except FileExistsError as error:
            raise DocumentError(409, "A Markdown file with that name already exists") from error
        except OSError as error:
            raise DocumentError(422, "Markdown file could not be renamed") from error
        return {"name": new_name, "content": data.decode("utf-8"), "revision": revision}


def save_document(source: sources.Source, suite_home: Path, history_home: Path,
                  name: str, content: str, revision: str, session_id: str) -> dict:
    if not _session.fullmatch(session_id):
        raise DocumentError(400, "Invalid editor session")
    try:
        fresh = content.encode("utf-8")
    except UnicodeEncodeError as error:
        raise DocumentError(400, "Markdown text must be UTF-8") from error
    if len(fresh) > MAX_BYTES:
        raise DocumentError(413, "Markdown text is too large")
    root = _root(source, suite_home)
    with _writes:
        path = _existing(root, name, suite_home)
        previous = _bytes(path)
        if _revision(previous) != revision:
            raise DocumentError(409, "Markdown file changed outside Keivotos; your unsaved text is still in the editor")
        if previous == fresh:
            return {"name": name, "content": content, "revision": revision}
        identity = hashlib.sha256(f"{source.source_id}\0{name}".encode()).hexdigest()
        history = history_home / "revisions" / identity / f"{session_id}.md"
        try:
            if not history.parent.resolve().is_relative_to(history_home.resolve()):
                raise DocumentError(403, "Markdown revision history is unavailable")
            history.parent.mkdir(parents=True, exist_ok=True)
            with history.open("xb") as archived:
                archived.write(previous)
                archived.flush()
                os.fsync(archived.fileno())
        except FileExistsError:
            if history.is_symlink() or not history.is_file():
                raise DocumentError(403, "Markdown revision history is unavailable")
            # This session's pre-edit bytes were already preserved.
        except OSError as error:
            raise DocumentError(422, "Could not preserve the previous Markdown revision") from error
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=root, prefix=".keivotos-language-",
                                             suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(fresh)
                stream.flush()
                os.fsync(stream.fileno())
            if _bytes(path) != previous:
                raise DocumentError(409, "Markdown file changed outside Keivotos; your unsaved text is still in the editor")
            os.replace(temporary, path)
        except OSError as error:
            raise DocumentError(422, "Markdown file could not be saved") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {"name": name, "content": content, "revision": _revision(fresh)}


def refresh_index(source: sources.Source, db_path: Path, name: str,
                  previous_name: str | None = None) -> None:
    with index.open_index(db_path) as connection:
        index.refresh_file(connection, source.source_id, Path(source.path), name, previous_name)
