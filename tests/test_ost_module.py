"""Isolated OST discovery, registration, containment and preservation contracts."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys
import zipfile
from unittest.mock import patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config
import database
from files_base import index, sources, serving
from modules import ost
from modules.ost import library, router


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    home = tmp_path / 'metadata'
    home.mkdir()
    media = tmp_path / 'music'
    media.mkdir()
    for folder in ['Album 2', 'Album 10']:
        (media / folder).mkdir()
        (media / folder / '曲 1.wav').write_bytes(b'original-audio')
    for name in ['Track 10.MP3', 'Track 2.mp3', '100%.flac', 'sample.wav',
                 'sample.ogg', 'sample.oga', 'sample.m4a', 'ignored.aac',
                 'ignored.mp4', 'cover.jpg', 'notes.md']:
        (media / name).write_bytes(b'original-audio')
    user = home / 'user.sqlite'
    db = home / 'base/files.sqlite'
    with sqlite3.connect(user) as connection:
        connection.row_factory = sqlite3.Row
        sources.ensure_sources_schema(connection)
        source = sources.register_source(connection, media, 'Soundtracks')
    with index.open_index(db) as connection:
        index.scan_source(connection, source.source_id, media)

    @contextmanager
    def connect():
        connection = sqlite3.connect(user)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()
    monkeypatch.setattr(router, 'get_user_db', connect)
    monkeypatch.setattr(database, 'get_user_db', connect)
    monkeypatch.setattr(config, 'USER_DB_PATH', user)
    monkeypatch.setattr(config, 'FILES_DB_PATH', db)
    monkeypatch.setattr(config, 'SUITE_HOME', home)
    return source, connect, media, db


def browse(source, parent='', offset=0, limit=120):
    return router.library(source.source_id, parent, offset, limit)


def test_descriptor_is_experimental_and_uses_existing_index_only(tmp_path):
    descriptor = ost.descriptor(tmp_path, 'test')
    assert descriptor.slug == 'ost' and descriptor.experimental and descriptor.disableable
    assert descriptor.database == tmp_path / 'base/files.sqlite'
    assert descriptor.credentials is None and descriptor.config_defaults == {}
    assert descriptor.user_schema_provider is None and descriptor.index_initializer is None
    assert descriptor.backup_components() == () and descriptor.background_tasks() == []
    assert descriptor.startup_hook is None
    assert descriptor.routers()[0] is router.router
    assert set(library.AUDIO_EXTENSIONS) == set(serving._INLINE_AUDIO)


def test_role_visible_sources_natural_order_and_pagination(catalog):
    source, connect, media, _ = catalog
    assert router.folders() == []
    with pytest.raises(HTTPException) as error:
        browse(source)
    assert error.value.status_code == 404
    ost.adopt(source.source_id)
    assert router.folders() == [{'source_id': source.source_id, 'name': 'Soundtracks', 'available': True}]
    result = browse(source)
    assert result['total'] == 9
    assert [item['name'] for item in result['items'][:2]] == ['Album 2', 'Album 10']
    tracks = [item['name'] for item in result['items'] if not item['is_dir']]
    assert tracks.index('Track 2.mp3') < tracks.index('Track 10.MP3')
    assert not any(item['name'].startswith('ignored') for item in result['items'])
    assert browse(source, '', 2, 3)['items'] == result['items'][2:5]
    assert browse(source, '', 1000, 3)['items'] == []
    assert browse(source, 'Album 2')['items'][0]['name'] == '曲 1.wav'
    assert browse(source, '.')['parent'] == ''
    with connect() as connection:
        sources.update_source(connection, source.source_id, visible=False)
    assert router.folders() == []
    with pytest.raises(HTTPException) as error:
        browse(source)
    assert error.value.status_code == 404
    assert (media / 'Track 2.mp3').read_bytes() == b'original-audio'


def test_discovery_opens_no_audio_bytes(catalog):
    source, _, _, _ = catalog
    ost.adopt(source.source_id)
    with patch.object(Path, 'read_bytes', side_effect=AssertionError('Do not read media')):
        assert browse(source)['total'] == 9


def test_nested_registered_roots_are_refused_even_with_stale_parent_index(catalog):
    source, connect, media, _ = catalog
    ost.adopt(source.source_id)
    with connect() as connection:
        nested = sources.register_source(connection, media / 'Album 2', 'Separate', role='files')
        sources.update_source(connection, nested.source_id, visible=False)
    assert 'Album 2' not in [item['name'] for item in browse(source)['items']]
    with pytest.raises(HTTPException) as error:
        browse(source, 'Album 2')
    assert error.value.status_code == 403
    with connect() as connection:
        sources.update_source(connection, nested.source_id, role='ost', visible=True)
    assert len(router.folders()) == 2
    with pytest.raises(HTTPException) as error:
        browse(source, 'Album 2')
    assert error.value.status_code == 403
    assert (media / 'Album 2/曲 1.wav').read_bytes() == b'original-audio'


@pytest.mark.parametrize('parent', ['../outside', '/outside', 'C:\\outside', 'Album 2/../Album 10'])
def test_relative_parent_guards(catalog, parent):
    source, _, _, _ = catalog
    ost.adopt(source.source_id)
    with pytest.raises(HTTPException) as error:
        browse(source, parent)
    assert error.value.status_code == 400


def test_symlinks_missing_files_and_private_data_remain_guarded(catalog, tmp_path):
    source, _, media, db = catalog
    ost.adopt(source.source_id)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'hidden.mp3').write_bytes(b'outside')
    (media / 'Escape').symlink_to(outside, target_is_directory=True)
    (media / 'Private').symlink_to(config.SUITE_HOME, target_is_directory=True)
    (media / 'alias.mp3').symlink_to(outside / 'hidden.mp3')
    with index.open_index(db) as connection:
        index.scan_source(connection, source.source_id, media)
    for parent in ['Escape', 'Private']:
        with pytest.raises(HTTPException) as error:
            browse(source, parent)
        assert error.value.status_code == 403
    assert not next(item for item in browse(source)['items'] if item['name'] == 'alias.mp3')['available']
    (media / 'Track 2.mp3').rename(media / 'preserved-moved.mp3')
    assert not next(item for item in browse(source)['items'] if item['name'] == 'Track 2.mp3')['available']
    media.rename(media.with_name('preserved-music'))
    assert router.folders()[0]['available'] is False
    with pytest.raises(HTTPException) as error:
        browse(source)
    assert error.value.status_code == 404


def test_release_and_forget_preserve_every_original(catalog):
    source, connect, media, _ = catalog
    before = {p.relative_to(media).as_posix(): p.read_bytes() for p in media.rglob('*') if p.is_file()}
    ost.adopt(source.source_id)
    ost.release(source.source_id)
    with connect() as connection:
        assert sources.get_source(connection, source.source_id).role == 'files'
    ost.adopt(source.source_id)
    ost.release(source.source_id, True)
    with connect() as connection:
        assert sources.get_source(connection, source.source_id) is None
    assert before == {p.relative_to(media).as_posix(): p.read_bytes() for p in media.rglob('*') if p.is_file()}


def test_storage_counts_shared_index_once_and_backup_contains_only_registry(catalog, tmp_path, monkeypatch):
    from services import storage_usage
    import backup_bundle
    source, _, media, _ = catalog
    ost.adopt(source.source_id)
    usage = storage_usage.library_files_usage()
    category = next(row for row in usage['categories'] if row['id'] == 'ost')
    assert category['name'] == 'OST'
    assert category['bytes'] == sum(p.stat().st_size for p in media.rglob('*') if p.is_file())
    assert usage['total_bytes'] == category['bytes']
    monkeypatch.setattr(backup_bundle, 'USER_DB_PATH', config.USER_DB_PATH)
    components = dict(backup_bundle.COMPONENTS)
    components['user_database'] = ('databases/user.sqlite', config.USER_DB_PATH)
    monkeypatch.setattr(backup_bundle, 'COMPONENTS', components)
    selection = {key: key == 'user_database' for key in components}
    monkeypatch.setattr(backup_bundle, 'get_backup_config', lambda: {'destination': str(tmp_path / 'backups'), 'components': selection})
    result = backup_bundle.create_backup_bundle(selection)
    with zipfile.ZipFile(result['path']) as archive:
        assert 'databases/user.sqlite' in archive.namelist()
        assert not any(name.endswith(('.mp3', '.wav', '.flac', 'ost.sqlite')) for name in archive.namelist())
        snapshot = tmp_path / 'backup-user.sqlite'
        snapshot.write_bytes(archive.read('databases/user.sqlite'))
    with sqlite3.connect(snapshot) as connection:
        assert connection.execute('SELECT role FROM files_sources WHERE source_id=?', (source.source_id,)).fetchone()[0] == 'ost'
