"""Real isolated app: injected startup/worker failure, Files survival and retry."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SERVER = r'''
import asyncio, os, sys
from dataclasses import replace
import database, lifecycle, suite_modules
from server import app
import uvicorn
# Only this disposable server process receives the failure injection.
database.init_user_db(set())
with database.get_user_db() as connection:
    suite_modules.ensure_schema(connection)
    suite_modules.set_enabled(connection, 'danbooru', True)
mode = os.environ['FIXTURE_FAILURE']
if mode == 'startup':
    original = lifecycle.init_data_db
    def initialize(enabled=None):
        raise OSError('fixture storage failure')
    lifecycle.init_data_db = initialize
    from routers import suite
    attempts = 0
    def retry_initialize(enabled=None):
        global attempts
        attempts += 1
        if attempts == 1:
            raise OSError('fixture retry failure')
        return original(enabled)
    suite.init_data_db = retry_initialize
else:
    owner = lifecycle.MODULE_REGISTRY.require('danbooru')
    async def crash():
        await asyncio.sleep(.05)
        raise RuntimeError('fixture worker failure')
    def workers():
        return owner.background_tasks() + [('fixture-crash', crash())]
    lifecycle.MODULE_REGISTRY = lifecycle.MODULE_REGISTRY.replacing(replace(owner, background_tasks_hook=workers))
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]))
'''


class ModuleFailureHttpTests(unittest.TestCase):
    def test_failed_owner_stays_enabled_files_survive_and_retry_recovers(self):
        for mode in ('startup', 'worker'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='keivotos-failure-') as temp:
                home = Path(temp)
                (home / 'config.json').write_text(json.dumps({
                    'default_library_created': True, 'automation_enabled': False,
                }))
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', 0))
                    port = probe.getsockname()[1]
                with (home / 'server.log').open('w+') as log:
                    process = subprocess.Popen(
                        [sys.executable, '-c', SERVER, str(port)], cwd=ROOT,
                        env={**os.environ, 'KEIVOTOS_HOME': str(home),
                             'PYTHONPATH': str(ROOT / 'backend'), 'FIXTURE_FAILURE': mode},
                        stdout=log, stderr=log,
                    )

                    def request(path, method='GET'):
                        req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', method=method)
                        try:
                            with urllib.request.urlopen(req, timeout=5) as response:
                                return response.status, json.load(response)
                        except urllib.error.HTTPError as exc:
                            return exc.code, json.load(exc)

                    try:
                        deadline = time.monotonic() + 20
                        while True:
                            try:
                                status, body = request('/api/suite/modules/danbooru/status')
                                if status == 200 and body['state'] == 'failed':
                                    break
                            except OSError:
                                pass
                            if process.poll() is not None or time.monotonic() > deadline:
                                self.fail('Isolated server did not report the injected failure')
                            time.sleep(.05)
                        self.assertTrue(body['error'])
                        self.assertEqual(request('/api/files/sources'), (200, []))
                        self.assertEqual(request('/api/user-settings/profile_name')[0], 200)
                        modules = request('/api/suite/modules')[1]
                        self.assertTrue(next(m for m in modules if m['id'] == 'danbooru')['enabled'])
                        self.assertEqual(request('/api/stats')[0], 503)
                        if mode == 'startup':
                            self.assertEqual(request('/api/suite/modules/danbooru/retry', 'POST')[0], 503)
                            self.assertEqual(request('/api/suite/modules/danbooru/status')[1]['state'], 'failed')
                            self.assertEqual(request('/api/files/sources')[0], 200)
                        code, recovered = request('/api/suite/modules/danbooru/retry', 'POST')
                        self.assertEqual(code, 200, recovered)
                        self.assertEqual(recovered['state'], 'running')
                        self.assertIsNone(recovered['error'])
                        self.assertEqual(request('/api/stats')[0], 200)
                        self.assertEqual(request('/api/suite/modules/danbooru/retry', 'POST')[0], 200)
                        self.assertEqual(request('/api/suite/modules/danbooru/disable', 'POST')[0], 200)
                        self.assertEqual(request('/api/suite/modules/danbooru/status')[1]['state'], 'disabled')
                        self.assertEqual(request('/api/suite/modules/danbooru/retry', 'POST')[0], 409)
                    finally:
                        if process.poll() is None:
                            if os.name == 'nt':
                                process.terminate()
                            else:
                                process.send_signal(signal.SIGINT)
                            try:
                                process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=5)
                        log.seek(0)
                        output = log.read()
                        self.assertIn('fixture ' + ('storage' if mode == 'startup' else 'worker') + ' failure', output)
                        self.assertNotIn('Exception in ASGI application', output)
                        self.assertNotIn('was never awaited', output)
