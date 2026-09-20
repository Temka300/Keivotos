"""Build current UI into scratch space and run timed modularization checks.

Requires external Node, Playwright and Chromium; does not install dependencies,
change frontend/dist, restart the live server or use the real library.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SERVER = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'backend'))
import server
from fastapi.staticfiles import StaticFiles
import uvicorn
server.FRONTEND_DIST = Path(sys.argv[1])
for route in server.app.routes:
    if getattr(route, 'name', None) == 'frontend':
        route.app = StaticFiles(directory=sys.argv[1], html=True)
uvicorn.run(server.app, host='127.0.0.1', port=int(sys.argv[2]))
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default=shutil.which('node'))
    parser.add_argument('--script', choices=('modularization', 'backup', 'danbooru', 'settings', 'import', 'modules', 'absence'), default='modularization')
    parser.add_argument('--output', required=True, type=Path, help='New directory for logs, screenshots and timing report')
    args = parser.parse_args()
    if not args.node:
        parser.error('Provide --node /path/to/node')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='keivotos-modularization-') as temporary:
        base = Path(temporary)
        home = base / 'home'
        home.mkdir()
        (home / 'config.json').write_text(json.dumps({'default_library_created': True}))
        if args.script == 'danbooru':
            from browser_library import seed_library
            seed_library(home)
        project = ROOT
        if args.script == 'absence':
            project = base / 'source'
            project.mkdir()
            shutil.copytree(ROOT / 'backend', project / 'backend',
                            ignore=shutil.ignore_patterns('danbooru', '__pycache__'))
            for name in ('app.py', 'config.json'):
                shutil.copy2(ROOT / name, project / name)
            shutil.copytree(ROOT / 'frontend', project / 'frontend',
                            ignore=shutil.ignore_patterns('node_modules', 'dist', 'danbooru'))
            (project / 'frontend/node_modules').symlink_to(ROOT / 'frontend/node_modules', target_is_directory=True)
            media = base / 'media'
            media.mkdir()
            (media / 'preserved.txt').write_text('Files-only preservation fixture')
        dist = project / 'frontend/dist' if args.script == 'absence' else base / 'frontend'
        with (output / 'build.log').open('w') as log:
            subprocess.run([args.node, 'node_modules/vite/bin/vite.js', 'build', '--outDir', str(dist)],
                           cwd=project / 'frontend', stdout=log, stderr=subprocess.STDOUT, check=True)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        context = base / 'context.json'
        context.write_text(json.dumps({'url': url, 'home': str(home), 'output': str(output), 'media': str(base / 'media')}))
        env = {**os.environ, 'KEIVOTOS_HOME': str(home)}
        with (output / 'server.log').open('w') as log:
            server = subprocess.Popen([sys.executable, '-c', SERVER, str(dist), str(port)],
                                      cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError('Isolated server exited; inspect server.log')
                    try:
                        with urllib.request.urlopen(url, timeout=.5):
                            break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError('Isolated server startup timed out')
                result = subprocess.run([args.node, str(ROOT / 'tests' / f'browser_{args.script}.cjs'), str(context)],
                                        cwd=ROOT, env=env, timeout=180)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
        if args.script == 'absence':
            assert not (home / 'modules/danbooru').exists(), 'Absent module created storage'
            with sqlite3.connect(home / 'user.sqlite') as connection:
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert 'user_settings' in tables
            assert not {'favorites', 'collections', 'collection_items'} & tables
            assert (base / 'media/preserved.txt').read_text() == 'Files-only preservation fixture'
        log_text = (output / 'server.log').read_text()
        if 'Traceback (most recent call last)' in log_text or 'ERROR:' in log_text:
            raise RuntimeError('Isolated server logged errors; inspect server.log')
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
