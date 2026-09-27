"""Scratch-only Language note tests; no live library is read or modified."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from files_base import index, sources
from module_registry import build_registry
from modules import language
from modules.language import documents, router


@pytest.fixture
def local(tmp_path, monkeypatch):
    media = tmp_path / "notes"
    media.mkdir()
    user_db = tmp_path / "user.sqlite"

    @contextmanager
    def connect():
        with sqlite3.connect(user_db) as connection:
            connection.row_factory = sqlite3.Row
            yield connection

    with connect() as connection:
        sources.ensure_sources_schema(connection)
        source = sources.register_source(connection, media, role="language")
    home = tmp_path / "suite"
    db = tmp_path / "files.sqlite"
    monkeypatch.setattr(router, "get_user_db", connect)
    monkeypatch.setattr(router, "_enabled", lambda: None)
    monkeypatch.setattr(router.config, "SUITE_HOME", home)
    monkeypatch.setattr(router.config, "FILES_DB_PATH", db)
    monkeypatch.setattr(router.config, "MODULE_REGISTRY", build_registry(home, "test"))
    return source, media, home, db, connect


def test_descriptor_folder_role_and_history_owner(local):
    source, media, home, db, connect = local
    descriptor = router.config.MODULE_REGISTRY.require("language")
    assert descriptor.experimental and descriptor.disableable and descriptor.adopt_hook
    with connect() as connection:
        sources.update_source(connection, source.source_id, role="files")
    import database
    original = database.get_user_db
    database.get_user_db = connect
    try:
        language.adopt(source.source_id)
        assert router.folders() == [{"source_id": source.source_id, "name": "notes"}]
        language.release(source.source_id)
        assert list(media.iterdir()) == []
    finally:
        database.get_user_db = original


def test_create_collision_rename_save_history_and_index(local, monkeypatch):
    source, media, home, db, connect = local
    monkeypatch.setattr(index, "scan_source", lambda *args, **kwargs: pytest.fail("whole-folder scan"))
    first = router.create_document(router.CreateRequest(source_id=source.source_id))
    second = router.create_document(router.CreateRequest(source_id=source.source_id))
    assert [first["name"], second["name"]] == ["New File.md", "New File (2).md"]
    with pytest.raises(HTTPException) as collision:
        router.rename_document(router.RenameRequest(source_id=source.source_id,
            name=first["name"], new_name=second["name"], revision=first["revision"]))
    assert collision.value.status_code == 409
    renamed = router.rename_document(router.RenameRequest(source_id=source.source_id,
        name=first["name"], new_name="My note.md", revision=first["revision"]))
    assert not (media / first["name"]).exists()
    assert (media / renamed["name"]).read_bytes() == b""
    session = "a" * 32
    saved = router.save_document(router.SaveRequest(source_id=source.source_id,
        name=renamed["name"], content="안녕 **world**", revision=renamed["revision"],
        session_id=session))
    later = router.save_document(router.SaveRequest(source_id=source.source_id,
        name=renamed["name"], content="Second edit", revision=saved["revision"],
        session_id=session))
    assert (media / "My note.md").read_text(encoding="utf-8") == "Second edit"
    history = list((home / "modules/language/revisions").rglob("*.md"))
    assert len(history) == 1 and history[0].read_bytes() == b""
    with index.open_index(db) as connection:
        rows = connection.execute("SELECT name, available, size FROM files_index WHERE source_id=?",
                                  (source.source_id,)).fetchall()
    assert any(row["name"] == "My note.md" and row["available"]
               and row["size"] == len(b"Second edit") for row in rows)
    assert any(row["name"] == "New File.md" and not row["available"] for row in rows)
    assert later["revision"] != saved["revision"]


def test_external_edit_conflict_preserves_both_versions(local):
    source, media, home, db, connect = local
    created = router.create_document(router.CreateRequest(source_id=source.source_id))
    (media / created["name"]).write_text("external edit", encoding="utf-8")
    with pytest.raises(HTTPException) as conflict:
        router.save_document(router.SaveRequest(source_id=source.source_id,
            name=created["name"], content="my edit", revision=created["revision"],
            session_id="b" * 32))
    assert conflict.value.status_code == 409
    assert (media / created["name"]).read_text() == "external edit"
    assert not list((home / "modules/language").rglob("*.md"))


@pytest.mark.parametrize("name", ["../escape.md", "a/b.md", "C:\\note.md", "CON.md",
                                   "bad.txt", " space.md", "trailing .md "])
def test_invalid_names_are_rejected(local, name):
    source, media, home, db, connect = local
    with pytest.raises(documents.DocumentError) as error:
        documents.valid_name(name)
    assert error.value.status_code == 400


def test_symlink_non_utf8_and_large_notes_are_not_edited(local, tmp_path):
    source, media, home, db, connect = local
    outside = tmp_path / "outside.md"
    outside.write_text("preserve")
    (media / "linked.md").symlink_to(outside)
    (media / "binary.md").write_bytes(b"\xff")
    (media / "large.md").write_bytes(b"x" * (documents.MAX_BYTES + 1))
    assert [row["name"] for row in router.list_documents(source.source_id)["files"]] == ["binary.md", "large.md"]
    for name, status in (("linked.md", 403), ("binary.md", 422), ("large.md", 413)):
        with pytest.raises(HTTPException) as error:
            router.read_document(source.source_id, name)
        assert error.value.status_code == status
    assert outside.read_text() == "preserve"


def test_role_change_blocks_operations_without_removing_notes(local):
    source, media, home, db, connect = local
    created = router.create_document(router.CreateRequest(source_id=source.source_id))
    with connect() as connection:
        sources.update_source(connection, source.source_id, role="files")
    with pytest.raises(HTTPException) as error:
        router.read_document(source.source_id, created["name"])
    assert error.value.status_code == 404
    assert (media / created["name"]).exists()
