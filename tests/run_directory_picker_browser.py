"""Run the Linux/WSL picker browser checks with disposable application data.

Requires an external Node + Playwright installation and its Chromium browser.
See docs/build/source.md. No live library or Danbooru import is used.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default=shutil.which('node'))
    args = parser.parse_args()
    if sys.platform == 'win32':
        parser.error('Run these Linux folder-picker checks inside Linux or WSL')
    if not args.node:
        parser.error('Node is not on PATH; provide --node /path/to/node')
    with tempfile.TemporaryDirectory(prefix='keivotos-picker-') as temporary:
        base = Path(temporary)
        home = base / 'metadata'
        home.mkdir()
        (home / 'config.json').write_text(json.dumps({'default_library_created': True}))
        fixture = base / 'Picker Media'
        for name in ('Upper', 'upper', 'Empty folder'):
            (fixture / name).mkdir(parents=True)
        (fixture / 'Upper' / 'note.txt').write_text('disposable fixture')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        context = base / 'context.json'
        context.write_text(json.dumps({'url': url, 'fixture': str(fixture), 'home': str(home)}))
        env = {**os.environ, 'KEIVOTOS_HOME': str(home)}
        with (base / 'server.log').open('w+') as log:
            server = subprocess.Popen(
                [sys.executable, 'app.py', '--no-browser', '--host', '127.0.0.1', '--port', str(port)],
                cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError('Isolated server exited during startup')
                    try:
                        with urllib.request.urlopen(url, timeout=.5):
                            break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError('Isolated server startup timed out')
                result = subprocess.run(
                    [args.node, str(ROOT / 'tests' / 'browser_directory_picker.cjs'), str(context)],
                    cwd=ROOT, env=env, timeout=180,
                )
                return result.returncode
            finally:
                if server.poll() is None:
                    os.killpg(server.pid, signal.SIGINT)
                    try:
                        server.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        os.killpg(server.pid, signal.SIGKILL)
                        server.wait()


if __name__ == '__main__':
    raise SystemExit(main())
