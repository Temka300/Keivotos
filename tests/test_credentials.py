"""Credential storage contracts; all secrets and files are disposable fixtures."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import credentials


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, 'CREDENTIALS_PATH', tmp_path / 'credentials.json')
    monkeypatch.setattr(credentials, '_uses_linux_vault', lambda: True)
    monkeypatch.delenv('DANBOORU_USERNAME', raising=False)
    monkeypatch.delenv('DANBOORU_API_KEY', raising=False)
    secrets = {}
    def operation(op, ref, secret=None):
        if op == 'get':
            return secrets.get(ref)
        if op == 'set':
            secrets[ref] = secret
        if op == 'delete':
            secrets.pop(ref, None)
    monkeypatch.setattr(credentials, '_vault', operation)
    return secrets


def test_linux_save_replace_reuse_clear_and_redaction(vault):
    status = credentials.save_credentials('dummy-user', 'dummy-secret-one')
    assert status == dict(username='dummy-user', has_api_key=True, has_saved_api_key=True,
                          has_saved_credentials=True, configured=True, source='saved')
    stored = credentials.CREDENTIALS_PATH.read_text()
    assert 'dummy-secret' not in stored + json.dumps(status)
    assert 'api_key_dpapi' not in stored
    if os.name != 'nt':
        assert credentials.CREDENTIALS_PATH.stat().st_mode & 0o777 == 0o600
    first = json.loads(stored)['linux_secret_service']['reference']
    credentials.save_credentials('dummy-user', 'dummy-secret-two')
    assert first not in vault
    assert list(vault.values()) == ['dummy-secret-two']
    credentials.save_credentials('renamed')
    assert credentials.saved_credentials() == ('renamed', 'dummy-secret-two')
    assert credentials.credential_environment()['DANBOORU_API_KEY'] == 'dummy-secret-two'
    assert credentials.clear_credentials()['configured'] is False
    assert not vault
    assert not credentials.CREDENTIALS_PATH.exists()


@pytest.mark.parametrize('reader', ['saved_credentials', 'effective_credentials'])
@pytest.mark.parametrize('mutation', ['replace', 'clear'])
def test_read_keeps_manifest_and_vault_consistent_during_mutation(vault, monkeypatch, reader, mutation):
    credentials.save_credentials('old-user', 'dummy-old-secret')
    reading_secret = threading.Event()
    release_reader = threading.Event()
    mutation_started = threading.Event()
    mutation_finished = threading.Event()
    original_vault = credentials._vault
    reader_thread = None

    def operation(op, ref, secret=None):
        if op == 'get' and threading.get_ident() == reader_thread:
            reading_secret.set()
            assert release_reader.wait(5), 'Reader was not released'
        return original_vault(op, ref, secret)

    def read():
        nonlocal reader_thread
        reader_thread = threading.get_ident()
        return getattr(credentials, reader)()

    def mutate():
        mutation_started.set()
        if mutation == 'replace':
            result = credentials.save_credentials('new-user', 'dummy-new-secret')
        else:
            result = credentials.clear_credentials()
        mutation_finished.set()
        return result

    monkeypatch.setattr(credentials, '_vault', operation)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(read)
        try:
            assert reading_secret.wait(5), 'Read never reached the vault'
            writing = pool.submit(mutate)
            assert mutation_started.wait(5), 'Mutation never started'
            assert not mutation_finished.wait(.2), 'Mutation invalidated an in-flight read'
        finally:
            release_reader.set()
        assert reading.result(timeout=5)[:2] == ('old-user', 'dummy-old-secret')
        writing.result(timeout=5)
    expected = ('new-user', 'dummy-new-secret') if mutation == 'replace' else (None, None)
    assert credentials.saved_credentials() == expected


def test_each_platform_preserves_other_platform_credentials(vault, monkeypatch):
    windows = dict(username='windows-user', api_key_dpapi='encrypted-windows', saved_at='old')
    credentials.CREDENTIALS_PATH.write_text(json.dumps(windows))
    credentials.save_credentials('linux-user', 'dummy-linux-secret')
    payload = json.loads(credentials.CREDENTIALS_PATH.read_text())
    assert all(payload[k] == v for k, v in windows.items())
    linux = payload['linux_secret_service']
    monkeypatch.setattr(credentials, '_uses_linux_vault', lambda: False)
    monkeypatch.setattr(credentials, '_protect', lambda value: 'encrypted-replacement')
    monkeypatch.setattr(credentials, '_unprotect', lambda value: 'dummy-windows-secret')
    assert credentials.saved_credentials() == ('windows-user', 'dummy-windows-secret')
    credentials.save_credentials('new-windows', 'dummy-windows-secret')
    assert json.loads(credentials.CREDENTIALS_PATH.read_text())['linux_secret_service'] == linux
    credentials.clear_credentials()
    assert json.loads(credentials.CREDENTIALS_PATH.read_text()) == {'linux_secret_service': linux}
    monkeypatch.setattr(credentials, '_uses_linux_vault', lambda: True)
    assert credentials.saved_credentials() == ('linux-user', 'dummy-linux-secret')
    credentials.CREDENTIALS_PATH.write_text(json.dumps({**windows, 'linux_secret_service': linux}))
    credentials.clear_credentials()
    assert json.loads(credentials.CREDENTIALS_PATH.read_text()) == windows


@pytest.mark.parametrize('failure', ['set', 'get', 'write'])
def test_failed_replacement_preserves_old_key_and_manifest(vault, monkeypatch, failure):
    credentials.save_credentials('old-user', 'dummy-old-secret')
    old_manifest = credentials.CREDENTIALS_PATH.read_bytes()
    old_secrets = dict(vault)
    original = credentials._vault
    def operation(op, ref, secret=None):
        if op == failure and ref not in old_secrets:
            raise RuntimeError('provider failure')
        return original(op, ref, secret)
    monkeypatch.setattr(credentials, '_vault', operation)
    if failure == 'write':
        monkeypatch.setattr(credentials, '_write_payload', lambda payload: (_ for _ in ()).throw(OSError('disk error')))
    with pytest.raises(RuntimeError, match='preserved'):
        credentials.save_credentials('new-user', 'dummy-new-secret')
    assert credentials.CREDENTIALS_PATH.read_bytes() == old_manifest
    assert vault == old_secrets


def test_clear_rolls_back_when_manifest_write_fails(vault, monkeypatch):
    credentials.save_credentials('dummy-user', 'dummy-secret')
    old_manifest = credentials.CREDENTIALS_PATH.read_bytes()
    old_secrets = dict(vault)
    monkeypatch.setattr(credentials, '_write_payload', lambda payload: (_ for _ in ()).throw(OSError('disk error')))
    with pytest.raises(RuntimeError, match='retry clearing'):
        credentials.clear_credentials()
    assert credentials.CREDENTIALS_PATH.read_bytes() == old_manifest
    assert vault == old_secrets


def test_locked_vault_and_environment_precedence(vault, monkeypatch):
    credentials.save_credentials('saved-user', 'dummy-saved-secret')
    monkeypatch.setenv('DANBOORU_USERNAME', 'env-user')
    assert credentials.effective_credentials() == ('env-user', 'dummy-saved-secret', 'environment')
    monkeypatch.setenv('DANBOORU_API_KEY', 'dummy-env-secret')
    monkeypatch.setattr(credentials, '_vault', lambda *args: (_ for _ in ()).throw(RuntimeError(credentials._VAULT_ERROR)))
    assert credentials.effective_credentials() == ('env-user', 'dummy-env-secret', 'environment')
    assert credentials.credentials_status()['configured'] is True
    monkeypatch.delenv('DANBOORU_API_KEY')
    with pytest.raises(RuntimeError, match='vault'):
        credentials.credentials_status()
    assert credentials.effective_credentials() == ('env-user', None, 'environment')
    with pytest.raises(RuntimeError, match='vault'):
        credentials.clear_credentials()
    assert credentials.CREDENTIALS_PATH.exists()


def test_missing_item_and_validation(vault):
    with pytest.raises(ValueError):
        credentials.save_credentials('', 'dummy-secret')
    with pytest.raises(ValueError):
        credentials.save_credentials('dummy-user', '')
    assert not vault
    credentials.save_credentials('dummy-user', 'dummy-secret')
    vault.clear()
    with pytest.raises(RuntimeError, match='missing'):
        credentials.credentials_status()
    assert not credentials.clear_credentials()['configured']


@pytest.mark.parametrize('failure', ['timeout', 'malformed', 'provider', 'wrong-type'])
def test_worker_failures_are_bounded_and_sanitized(monkeypatch, failure):
    def run(args, **kwargs):
        assert 'dummy-secret' not in str(args)
        assert json.loads(kwargs['input'])['secret'] == 'dummy-secret'
        assert kwargs['timeout'] == 10
        if failure == 'timeout':
            raise subprocess.TimeoutExpired(args, 10, output='dummy-secret')
        return SimpleNamespace(returncode=0, stdout={
            'malformed': 'dummy-secret', 'provider': '{"error": "dummy-secret"}',
            'wrong-type': '{"value": 123}',
        }[failure])
    monkeypatch.setattr(credentials.subprocess, 'run', run)
    with pytest.raises(RuntimeError) as exc:
        credentials._vault('set', 'reference', 'dummy-secret')
    assert 'dummy-secret' not in str(exc.value)


def test_routes_expose_actionable_vault_errors(vault, monkeypatch):
    from fastapi import HTTPException
    from modules.danbooru.routers import tools
    for operation, route in [('credentials_status', tools.get_danbooru_credentials),
                             ('clear_credentials', tools.delete_danbooru_credentials)]:
        with patch.object(tools, operation, side_effect=RuntimeError(credentials._VAULT_ERROR)):
            with pytest.raises(HTTPException) as exc:
                route()
            assert exc.value.status_code == 400
            assert exc.value.detail == credentials._VAULT_ERROR
