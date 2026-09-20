"""While-running backup scheduling and narrowly owned automatic retention."""
from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import threading
import time
import uuid

from config import AUTOMATIC_BACKUP_STATE_FILE, get_backup_options
from maintenance import exclusive_tool_operation

logger = logging.getLogger('keivotos.backups')
_state_lock = threading.RLock()
_running = False


def _read_state() -> dict:
    try:
        value = json.loads(AUTOMATIC_BACKUP_STATE_FILE.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(value: dict) -> None:
    AUTOMATIC_BACKUP_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = AUTOMATIC_BACKUP_STATE_FILE.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(AUTOMATIC_BACKUP_STATE_FILE)


def automatic_backup_status() -> dict:
    with _state_lock:
        value = _read_state()
        return {'running': _running, 'last_at': value.get('last_at'),
                'last_result': value.get('last_result'), 'last_success_at': value.get('last_success_at')}


def _digest(path: Path) -> str:
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _retain_owned(state: dict, directory: Path, retention: int) -> None:
    """Never select by glob alone: only unchanged files recorded by this app."""
    entries = state.get('owned', [])
    eligible = [entry for entry in entries if isinstance(entry, dict) and entry.get('directory') == str(directory)]
    # Entries are recorded oldest first. A verified newer backup already exists.
    removed = []
    for entry in eligible[:-retention]:
        name = entry.get('name', '')
        identity = entry.get('id', '')
        if (not isinstance(name, str) or not isinstance(identity, str)
                or len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity)
                or name != f'automatic_{identity}.keivotosbk'):
            continue
        path = directory / name
        try:
            if path.is_symlink() or path.resolve().parent != directory:
                continue
            if not path.exists():
                removed.append(entry)
                continue
            if _digest(path) != entry.get('sha256'):
                logger.warning('Preserving modified automatic backup: %s', name)
                continue
            from backup_bundle import inspect_backup_bundle
            if inspect_backup_bundle(path).get('automatic_id') != identity:
                continue
            path.unlink()
            removed.append(entry)
            logger.info('Retired automatic backup: %s', name)
        except Exception:
            logger.exception('Could not retire automatic backup: %s', name)
    state['owned'] = [entry for entry in entries if entry not in removed]


def run_automatic_backup() -> bool:
    """Return False when busy/disabled; contention is a deferral, not a failure."""
    global _running
    with _state_lock:
        if _running or not get_backup_options()['enabled']:
            return False
        _running = True
    try:
        # Keep configuration, backup, ledger and retention in one maintenance window.
        with exclusive_tool_operation('automatic backup', wait=False):
            if not get_backup_options()['enabled']:
                return False
            from backup_bundle import create_backup_bundle
            try:
                identity = uuid.uuid4().hex
                result = create_backup_bundle(automatic_id=identity)
                path = Path(result['path']).resolve()
                digest = _digest(path)
                with _state_lock:
                    state = _read_state()
                    entries = state.get('owned', [])
                    if not isinstance(entries, list):
                        entries = []
                    state['owned'] = entries + [{'directory': str(path.parent), 'name': path.name,
                                                'id': identity, 'sha256': digest}]
                    now = datetime.now().astimezone().isoformat()
                    state.update(last_at=now, last_success_at=now, last_result='success')
                    # If ownership cannot be persisted, preserve all prior backups.
                    _write_state(state)
                _retain_owned(state, path.parent, get_backup_options()['retention'])
                with _state_lock:
                    _write_state(state)
                return True
            except Exception:
                logger.exception('Automatic backup failed')
                with _state_lock:
                    state = _read_state()
                    state.update(last_at=datetime.now().astimezone().isoformat(), last_result='failed')
                    _write_state(state)
                return True
    except RuntimeError:
        logger.info('Automatic backup deferred while another operation is active')
        return False
    finally:
        with _state_lock:
            _running = False


class BackupSchedule:
    def __init__(self):
        self.signature = None
        self.next_at = None

    def tick(self, now: float | None = None) -> None:
        real_clock = now is None
        now = time.monotonic() if real_clock else now
        options = get_backup_options()
        signature = (options['enabled'], options['frequency_minutes'])
        if signature != self.signature:
            self.signature = signature
            self.next_at = now + options['frequency_minutes'] * 60 if options['enabled'] else None
        if self.next_at is not None and now >= self.next_at:
            completed = True
            try:
                completed = run_automatic_backup()
            finally:
                # Even an unwritable status ledger must not create a retry storm.
                # Busy operations defer briefly; all attempts wait a full interval.
                self.next_at = (time.monotonic() if real_clock else now) + (options['frequency_minutes'] * 60 if completed else 30)


async def automatic_backup_loop(stop: asyncio.Event) -> None:
    schedule = BackupSchedule()
    while not stop.is_set():
        try:
            await asyncio.to_thread(schedule.tick)
        except Exception:
            logger.exception('Automatic backup scheduler could not update its state')
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
