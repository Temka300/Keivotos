"""HTTP admission checks against the complete installed module route inventory."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
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
sys.path.insert(0, str(ROOT / 'backend'))


class ModuleHttpGuardTests(unittest.TestCase):
    def test_all_module_routes_block_disabled_and_live_toggles_reopen_them(self):
        from config import MODULE_REGISTRY

        inventory = {(method, route.path) for router in MODULE_REGISTRY.require('danbooru').routers()
                     for route in router.routes for method in route.methods}
        self.assertGreater(len(inventory), 50)
        with tempfile.TemporaryDirectory(prefix='keivotos-http-guard-') as temp:
            home = Path(temp)
            (home / 'config.json').write_text(json.dumps({
                'default_library_created': True, 'automation_enabled': False,
            }))
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            with (home / 'server.log').open('w+') as log:
                process = subprocess.Popen(
                    [sys.executable, str(ROOT / 'app.py'), '--no-browser', '--host', '127.0.0.1', '--port', str(port)],
                    cwd=ROOT, env={**os.environ, 'KEIVOTOS_HOME': str(home)},
                    stdout=log, stderr=log,
                )

                def request(path, method='GET'):
                    req = urllib.request.Request(
                        f'http://127.0.0.1:{port}{path}', method=method,
                        data=b'{}' if method in {'POST', 'PUT', 'PATCH'} else None,
                        headers={'Content-Type': 'application/json'},
                    )
                    try:
                        with urllib.request.urlopen(req, timeout=5) as response:
                            return response.status, json.load(response)
                    except urllib.error.HTTPError as exc:
                        return exc.code, json.load(exc)

                try:
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            status, _ = request('/api/suite/modules')
                            if status == 200:
                                break
                        except OSError:
                            pass
                        if process.poll() is not None or time.monotonic() > deadline:
                            self.fail('Isolated server did not become ready')
                        time.sleep(.05)
                    for method, path in sorted(inventory):
                        with self.subTest(method=method, path=path):
                            path = re.sub(r'\{[^}]+\}', '1', path)
                            status, body = request(path, method)
                            self.assertEqual(status, 409, body)
                            self.assertIn('Enable Danbooru', body['detail'])
                    self.assertFalse(list(home.rglob('danbooru.sqlite')))
                    self.assertEqual(request('/api/files/sources'), (200, []))
                    code, recovery = request('/api/local-recovery/checkpoint', 'POST')
                    self.assertEqual(code, 200, recovery)
                    self.assertEqual(Path(recovery['directory']), home / 'local_recovery' / 'user_database')
                    self.assertEqual(recovery['preserved_count'], 0)
                    self.assertFalse(list(home.rglob('danbooru.sqlite')))
                    self.assertEqual(request('/api/user-settings/profile_name')[0], 200)
                    self.assertEqual(request('/api/suite/modules/danbooru/enable', 'POST')[0], 200)
                    self.assertEqual(request('/api/stats')[0], 200)
                    self.assertEqual(request('/api/automation')[0], 200)
                    self.assertEqual(request('/api/suite/modules/danbooru/disable', 'POST')[0], 200)
                    self.assertEqual(request('/api/stats')[0], 409)
                    self.assertTrue(list(home.rglob('danbooru.sqlite')))
                    self.assertEqual(request('/api/suite/modules/danbooru/enable', 'POST')[0], 200)
                    self.assertEqual(request('/api/stats')[0], 200)
                finally:
                    if process.poll() is None:
                        if os.name == "nt":
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
                    self.assertNotIn('Traceback', output)
                    self.assertNotIn('ERROR:', output)


class ModuleAdmissionTests(unittest.TestCase):
    def test_transition_rejects_admitted_request_and_request_rejects_transition(self):
        import maintenance
        with maintenance.module_operation():
            with self.assertRaisesRegex(RuntimeError, 'module operations'):
                with maintenance.module_transition():
                    self.fail('Disable must not race admitted work')
        with maintenance.module_transition():
            with self.assertRaises(RuntimeError):
                with maintenance.module_operation():
                    self.fail('New work must not enter during disable')
        with maintenance.module_transition():
            pass

    def test_http_guard_releases_lease_on_rejection_and_handler_error(self):
        from unittest.mock import patch
        import maintenance
        from server import module_guard
        from fastapi import HTTPException

        with patch('suite_modules.require_enabled', side_effect=RuntimeError('disabled')):
            guard = module_guard('danbooru')()
            with self.assertRaises(HTTPException):
                next(guard)
        self.assertEqual(maintenance._module_operations, 0)
        with patch('suite_modules.require_enabled'):
            guard = module_guard('danbooru')()
            next(guard)
            with self.assertRaisesRegex(ValueError, 'handler error'):
                guard.throw(ValueError('handler error'))
        self.assertEqual(maintenance._module_operations, 0)
