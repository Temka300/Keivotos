"""Diagnostics use fixed destinations and persist preferences in isolated storage."""
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import config
from fastapi import HTTPException
from pydantic import ValidationError
from routers import storage
from runtime_logging import _UsefulRuntimeAccessFilter


def test_verbose_logging_changes_filter_immediately():
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s %s %s %s %s',
                               ('local', 'GET', '/api/storage', '1.1', 200), None)
    access_filter = _UsefulRuntimeAccessFilter()
    with patch.dict(config._cfg, {'verbose_logging': False}):
        assert not access_filter.filter(record)
        config._cfg['verbose_logging'] = True
        assert access_filter.filter(record)
        config._cfg['verbose_logging'] = False
        record.args = ('local', 'GET', '/api/storage', '1.1', 500)
        assert access_filter.filter(record)


def test_preferences_survive_restart(tmp_path):
    code = """
import config
from routers.storage import DiagnosticsPreferences, update_diagnostics
update_diagnostics(DiagnosticsPreferences(verbose_logging=True, show_experimental_modules=True))
"""
    env = {**os.environ, 'KEIVOTOS_HOME': str(tmp_path), 'PYTHONPATH': str(ROOT / 'backend')}
    subprocess.run([sys.executable, '-c', code], env=env, check=True)
    subprocess.run([sys.executable, '-c', "import config; assert all(config.get_diagnostics_preferences().values())"], env=env, check=True)


def test_preferences_reject_extra_keys_and_non_booleans():
    for values in ({'verbose_logging': 'yes', 'show_experimental_modules': False},
                   {'verbose_logging': True, 'show_experimental_modules': False, 'path': '/tmp'}):
        with pytest.raises(ValidationError):
            storage.DiagnosticsPreferences(**values)


def test_open_fixed_targets_and_missing_file(tmp_path):
    log = tmp_path / 'runtime.log'
    log.write_text('fixture')
    with patch.multiple(config, SUITE_HOME=tmp_path, LOG_DIR=tmp_path, RUNTIME_LOG_FILE=log), \
         patch.object(storage.sys, 'platform', 'linux'), patch.object(storage.subprocess, 'Popen') as launch:
        for target, expected in [('data', tmp_path), ('logs', tmp_path), ('runtime', log)]:
            assert storage.open_diagnostics(target) == {'status': 'opened'}
            assert launch.call_args.args[0] == ['xdg-open', str(expected)]
        launch.side_effect = OSError('fixture unavailable desktop')
        with pytest.raises(HTTPException) as caught:
            storage.open_diagnostics('runtime')
        assert caught.value.status_code == 503
    with patch.object(config, 'RUNTIME_LOG_FILE', tmp_path / 'missing'):
        with pytest.raises(HTTPException) as caught:
            storage.open_diagnostics('runtime')
        assert caught.value.status_code == 404


def test_log_symlink_cannot_open_outside_log_directory(tmp_path):
    logs = tmp_path / 'logs'
    logs.mkdir()
    outside = tmp_path / 'private.txt'
    outside.write_text('fixture')
    log = logs / 'runtime.log'
    log.symlink_to(outside)
    with patch.multiple(config, LOG_DIR=logs, RUNTIME_LOG_FILE=log), patch.object(storage.subprocess, 'Popen') as launch:
        with pytest.raises(HTTPException) as caught:
            storage.open_diagnostics('runtime')
        assert caught.value.status_code == 409
        launch.assert_not_called()


def test_open_backup_folder_resolves_configured_destination(tmp_path):
    destination = tmp_path / 'backups'
    with patch.object(config, 'get_backup_config', return_value={'destination': str(destination)}), \
         patch.object(storage.sys, 'platform', 'linux'), patch.object(storage.subprocess, 'Popen') as launch:
        assert storage.open_diagnostics('backups') == {'status': 'opened'}
        assert destination.is_dir()
        assert launch.call_args.args[0] == ['xdg-open', str(destination.resolve())]


def test_planned_modules_cannot_be_enabled_as_empty_modules():
    from routers import suite
    planned = suite.planned_modules()
    assert {entry['id'] for entry in planned} == {'manga', 'youtube'}
    for entry in planned:
        with pytest.raises(HTTPException) as caught:
            suite.enable_module(entry['id'])
        assert caught.value.status_code == 404
