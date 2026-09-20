"""Isolated automatic scheduling, ownership, retention and configuration safety."""
import json
from pathlib import Path
import sqlite3
import sys
import threading
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import automatic_backups as automatic
import backup_bundle as bundles
import config
import maintenance
from models import BackupOptions


@pytest.fixture
def backup_home(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    home.mkdir()
    user = home / 'user.sqlite'
    with sqlite3.connect(user) as connection:
        connection.execute('create table marker(value text)')
        connection.execute("insert into marker values('preserve me')")
    options = {'enabled': True, 'location':'default', 'custom_location':'', 'retention':2, 'frequency_minutes':15}
    destination = home / 'backups'
    monkeypatch.setattr(config, '_cfg', {'backup_options':options, 'backup_components':{'user_database':True, 'file_attachments':False}})
    monkeypatch.setattr(config, 'DEFAULT_BACKUP_DIR', destination)
    monkeypatch.setattr(config, 'RUNTIME_CONFIG_FILE', home / 'config.json')
    monkeypatch.setattr(automatic, 'AUTOMATIC_BACKUP_STATE_FILE', home / 'automatic-backups.json')
    monkeypatch.setattr(bundles, 'COMPONENTS', {'user_database':('databases/user.sqlite',user)})
    monkeypatch.setattr(bundles, 'USER_DB_PATH', user)
    return home, destination, options


def test_retention_only_deletes_recorded_unchanged_automatic_bundles(backup_home):
    home, destination, options = backup_home
    manual = Path(bundles.create_backup_bundle()['path'])
    assert automatic.run_automatic_backup()
    first = next(destination.glob('automatic_*.keivotosbk'))
    copy = destination / 'automatic_user_copy.keivotosbk'
    copy.write_bytes(first.read_bytes())
    recovery = home / 'local_recovery'
    recovery.mkdir()
    (recovery/'preserved').write_text('keep')
    for _ in range(3):
        assert automatic.run_automatic_backup()
    state = json.loads(automatic.AUTOMATIC_BACKUP_STATE_FILE.read_text())
    assert len(state['owned']) == 2
    assert not first.exists()
    assert manual.exists() and copy.exists() and (recovery/'preserved').read_text() == 'keep'
    for entry in state['owned']:
        assert bundles.inspect_backup_bundle(destination/entry['name'])['automatic_id'] == entry['id']
    assert automatic.automatic_backup_status()['last_result'] == 'success'


def test_failure_never_prunes_and_modified_backups_are_preserved(backup_home, monkeypatch):
    home, destination, options = backup_home
    options['retention'] = 1
    assert automatic.run_automatic_backup()
    first = next(destination.glob('automatic_*.keivotosbk'))
    original = bundles.create_backup_bundle
    monkeypatch.setattr(bundles, 'create_backup_bundle', Mock(side_effect=OSError('disk full fixture')))
    assert automatic.run_automatic_backup()
    assert first.exists()
    assert automatic.automatic_backup_status()['last_result'] == 'failed'
    assert automatic.automatic_backup_status()['last_success_at']
    monkeypatch.setattr(bundles, 'create_backup_bundle', original)
    first.write_bytes(b'changed by user')
    assert automatic.run_automatic_backup()
    assert first.read_bytes() == b'changed by user'


def test_busy_job_defers_and_schedule_has_no_catchup(backup_home, monkeypatch):
    _, destination, options = backup_home
    schedule = automatic.BackupSchedule()
    schedule.tick(0)
    schedule.tick(899)
    assert not destination.exists()
    monkeypatch.setattr(maintenance, '_active_tool_id', 'fixture')
    schedule.tick(900)
    assert not destination.exists()
    assert automatic.automatic_backup_status()['last_result'] is None
    monkeypatch.setattr(maintenance, '_active_tool_id', None)
    schedule.tick(930)
    assert len(list(destination.glob('*.keivotosbk'))) == 1
    schedule.tick(10000)
    assert len(list(destination.glob('*.keivotosbk'))) == 2
    schedule.tick(10000)
    assert len(list(destination.glob('*.keivotosbk'))) == 2
    options['enabled'] = False
    schedule.tick(100000)
    assert schedule.next_at is None


def test_busy_maintenance_is_not_queued(backup_home):
    acquired = threading.Event()
    release = threading.Event()
    def hold():
        with maintenance.exclusive_tool_operation('fixture'):
            acquired.set()
            release.wait(5)
    worker = threading.Thread(target=hold)
    worker.start()
    try:
        assert acquired.wait(2)
        assert automatic.run_automatic_backup() is False
    finally:
        release.set()
        worker.join()


def test_custom_location_roundtrip_and_old_location_is_preserved(backup_home, tmp_path):
    _, default, options = backup_home
    automatic.run_automatic_backup()
    old = list(default.glob('*.keivotosbk'))
    custom = tmp_path/'custom'
    selected = {'user_database':True, 'file_attachments':False}
    result = bundles.update_backup_configuration(selected, {**options, 'location':'custom', 'custom_location':str(custom)})
    assert result['destination'] == str(custom)
    assert json.loads(config.RUNTIME_CONFIG_FILE.read_text())['backup_options']['location'] == 'custom'
    for _ in range(3): automatic.run_automatic_backup()
    assert all(path.exists() for path in old)
    assert len(list(custom.glob('automatic_*.keivotosbk'))) == 2
    # A user-owned directory with the old reserved staging name is not removed.
    protected = custom/'.danbooru-backup-staging'
    protected.mkdir()
    (protected/'personal').write_text('keep')
    bundles.create_backup_bundle()
    assert (protected/'personal').read_text() == 'keep'


def test_invalid_locations_and_options_never_save(backup_home, monkeypatch, tmp_path):
    save = Mock()
    monkeypatch.setattr(bundles, 'save_config', save)
    for value in ('relative/path', '', str(config.RECOVERY_DIR/'nested')):
        with pytest.raises(ValueError):
            bundles.update_backup_configuration({'user_database':True}, {'location':'custom', 'custom_location':value})
    save.assert_not_called()
    for values in ({'retention':0}, {'retention':6}, {'frequency_minutes':10}, {'enabled':'yes'}, {'retention':True}):
        with pytest.raises(ValidationError): BackupOptions(**values)


def test_symlink_and_unrecorded_files_are_not_pruned(backup_home, tmp_path):
    _, destination, options = backup_home
    options['retention'] = 1
    automatic.run_automatic_backup()
    first = next(destination.glob('automatic_*.keivotosbk'))
    outside = tmp_path/'preserved.keivotosbk'
    outside.write_bytes(first.read_bytes())
    first.unlink()
    first.symlink_to(outside)
    automatic.run_automatic_backup()
    assert first.is_symlink() and outside.exists()


def test_shutdown_waits_for_inflight_backup_thread(monkeypatch):
    import asyncio
    entered = threading.Event()
    release = threading.Event()
    def work(self):
        entered.set()
        release.wait(5)
    monkeypatch.setattr(automatic.BackupSchedule, 'tick', work)
    async def exercise():
        stop = asyncio.Event()
        task = asyncio.create_task(automatic.automatic_backup_loop(stop))
        try:
            for _ in range(100):
                if entered.is_set(): break
                await asyncio.sleep(.01)
            assert entered.is_set()
            stop.set()
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), .05)
        finally:
            release.set()
            await asyncio.wait_for(task, 2)
    asyncio.run(exercise())


def test_lost_ledger_and_preexisting_partial_files_are_preserved(backup_home, monkeypatch):
    _, destination, options = backup_home
    options['retention'] = 1
    automatic.run_automatic_backup()
    orphan = next(destination.glob('automatic_*.keivotosbk'))
    automatic.AUTOMATIC_BACKUP_STATE_FILE.write_text('invalid ledger')
    automatic.run_automatic_backup()
    assert orphan.exists()
    monkeypatch.setattr(bundles.time, 'time', lambda: 1800000000)
    partial = destination/'backup_1800000000.keivotosbk.partial'
    partial.write_bytes(b'preserved earlier work')
    created = bundles.create_backup_bundle()
    assert created['name'] == 'backup_1800000000_2.keivotosbk'
    assert partial.read_bytes() == b'preserved earlier work'


def test_backup_reference_config_omits_custom_location(backup_home):
    _, _, options = backup_home
    options.update(location='custom', custom_location='/private/backup-location')
    snapshot = config.runtime_config_snapshot()
    assert snapshot['backup_options']['custom_location'] == ''
    assert options['custom_location'] == '/private/backup-location'


def test_unwritable_status_does_not_retry_every_scheduler_tick(backup_home, monkeypatch):
    work = Mock(side_effect=OSError('status storage unavailable'))
    monkeypatch.setattr(automatic, 'run_automatic_backup', work)
    schedule = automatic.BackupSchedule()
    schedule.tick(0)
    with pytest.raises(OSError): schedule.tick(900)
    schedule.tick(905)
    assert work.call_count == 1
    assert schedule.next_at == 1800


def test_remembered_selection_survives_disabled_configuration(backup_home):
    home, _, options = backup_home
    options = {**options, 'remembered_components': {'sidecars': True, 'sidecar_history': False}}
    bundles.update_backup_configuration({'user_database': True}, options)
    loaded = json.loads((home / 'config.json').read_text())
    assert loaded['backup_options']['remembered_components'] == options['remembered_components']
    assert config.get_backup_options()['remembered_components'] == options['remembered_components']
