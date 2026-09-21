"""Isolated Video discovery, ownership and diagnostic contracts."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from files_base import index, sources
from modules import video
from modules.video import router
import database


@pytest.fixture
def library(tmp_path, monkeypatch):
    user = tmp_path / 'user.sqlite'
    media = tmp_path / 'media'
    media.mkdir()
    for name in ['B.webm', 'a.MP4', '100%.m4v', 'ignored.txt', 'unsupported.mkv']:
        (media / name).write_bytes(b'fixture')
    with sqlite3.connect(user) as connection:
        connection.row_factory = sqlite3.Row
        sources.ensure_sources_schema(connection)
        source = sources.register_source(connection, media)
    db = tmp_path / 'files.sqlite'
    with index.open_index(db) as connection:
        index.scan_source(connection, source.source_id, media)
    @contextmanager
    def get_user_db():
        connection = sqlite3.connect(user)
        connection.row_factory = sqlite3.Row
        try: yield connection
        finally: connection.close()
    monkeypatch.setattr(router, 'get_user_db', get_user_db)
    monkeypatch.setattr(database, 'get_user_db', get_user_db)
    monkeypatch.setattr(router, 'FILES_DB_PATH', db)
    return source, get_user_db, media


def test_discovery_role_visibility_literal_search_and_pagination(library):
    source, connect, media = library
    assert router.library('', 0, 120)['total'] == 0
    video.adopt(source.source_id)
    assert router.library('', 0, 120)['total'] == 4
    assert router.library('%', 0, 120)['items'][0]['name'] == '100%.m4v'
    assert len(router.library('', 1, 2)['items']) == 2
    assert router.library('A.MP4', 0, 120)['total'] == 1
    with connect() as connection:
        sources.update_source(connection, source.source_id, visible=False)
    assert router.library('', 0, 120)['total'] == 0
    assert (media / 'a.MP4').read_bytes() == b'fixture'


def test_release_and_forget_only_change_registration(library):
    source, connect, media = library
    before = {p.name:p.read_bytes() for p in media.iterdir()}
    video.adopt(source.source_id)
    video.release(source.source_id)
    with connect() as connection: assert sources.get_source(connection, source.source_id).role == 'files'
    video.adopt(source.source_id)
    video.release(source.source_id, True)
    with connect() as connection: assert sources.get_source(connection, source.source_id) is None
    assert before == {p.name:p.read_bytes() for p in media.iterdir()}


def test_failure_log_requires_known_visible_video_and_contains_context(library, caplog):
    source, _, _ = library
    video.adopt(source.source_id)
    assert router.playback_error(router.PlaybackFailure(source_id=source.source_id, path='a.MP4', reason='decode')) == {'status':'logged'}
    assert 'a.MP4' in caplog.text and 'decode' in caplog.text
    for path in ['../outside.mp4', 'ignored.txt', '/unknown.mp4']:
        with pytest.raises(HTTPException) as error:
            router.playback_error(router.PlaybackFailure(source_id=source.source_id, path=path, reason='decode'))
        assert error.value.status_code == 404


def test_descriptor_uses_shared_index_and_has_no_new_durable_state(tmp_path):
    descriptor = video.descriptor(tmp_path, 'test')
    assert descriptor.database == tmp_path / 'base/files.sqlite'
    assert descriptor.backup_components() == ()
    assert descriptor.background_tasks() == []
    assert descriptor.disableable
