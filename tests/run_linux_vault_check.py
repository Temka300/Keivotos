"""Opt-in real Secret Service check using a private bus and disposable keyring.

Run with Linux Python; requires dbus-run-session and gnome-keyring-daemon.
No real credentials, library data, or Danbooru requests are used.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'disposable-vault-test-password'


def check(daemon_path: str, base: Path) -> None:
    def client(code):
        return subprocess.run([sys.executable, '-c', 'import credentials; ' + code],
                              check=True, capture_output=True, text=True, timeout=35)

    def start():
        process = subprocess.Popen([daemon_path, '--foreground', '--unlock', '--components=secrets',
                                    '--control-directory', str(base / 'control')],
                                   stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.stdin.write(PASSWORD.encode())
        process.stdin.close()
        for _ in range(50):
            try:
                client("credentials._vault('get', 'readiness-check')")
                return process
            except subprocess.CalledProcessError:
                if process.poll() is not None:
                    break
                time.sleep(.1)
        process.terminate()
        process.wait(timeout=10)
        raise RuntimeError('Disposable vault failed to start')

    def stop(process):
        process.terminate()
        process.wait(timeout=10)

    daemon = start()
    try:
        client("assert credentials.save_credentials('dummy-user', 'dummy-secret-one')['configured']")
        client("assert credentials.saved_credentials(strict=True) == ('dummy-user', 'dummy-secret-one')")
        stop(daemon)
        daemon = start()
        client("assert credentials.saved_credentials(strict=True) == ('dummy-user', 'dummy-secret-one')")
        client("credentials.save_credentials('dummy-user', 'dummy-secret-two')")
        client("assert credentials.saved_credentials(strict=True) == ('dummy-user', 'dummy-secret-two')")
        import secretstorage
        def item_count():
            with secretstorage.dbus_init() as connection:
                collection = secretstorage.get_default_collection(connection)
                return len(list(collection.search_items({'service': 'Keivotos Danbooru'})))
        assert item_count() == 1, 'Replacement left stale vault items'
        for path in base.rglob('*'):
            if path.is_file():
                assert b'dummy-secret-' not in path.read_bytes(), f'Plaintext key in {path.name}'
        print('PASS: real vault save, client/daemon restart, replacement, no plaintext keys on disk')
        with secretstorage.dbus_init() as connection:
            collection = secretstorage.get_default_collection(connection)
            collection.lock()
        client("\ntry: credentials.credentials_status()\nexcept RuntimeError as error: assert 'vault' in str(error)\nelse: raise AssertionError('Locked vault was accepted')")
        print('PASS: locked vault fails without an unlock prompt')
        stop(daemon)
        daemon = start()
        client("assert not credentials.clear_credentials()['configured']")
        client("assert credentials.saved_credentials() == (None, None)")
        assert item_count() == 0, 'Removed secret remains in vault'
        print('PASS: real vault removal persists across client restart')
    finally:
        if daemon.poll() is None:
            stop(daemon)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--daemon', default=shutil.which('gnome-keyring-daemon'))
    parser.add_argument('--isolated', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.isolated:
        check(args.daemon, Path(args.isolated))
        return
    if sys.platform != 'linux' or not args.daemon or not shutil.which('dbus-run-session'):
        parser.error('Requires Linux, dbus-run-session, and gnome-keyring-daemon (or --daemon PATH)')
    with tempfile.TemporaryDirectory(prefix='keivotos-vault-') as temporary:
        base = Path(temporary)
        for name in ('home', 'data', 'config', 'runtime', 'control', 'app'):
            (base / name).mkdir(mode=0o700)
        env = {**os.environ, 'HOME': str(base / 'home'), 'XDG_DATA_HOME': str(base / 'data'),
               'XDG_CONFIG_HOME': str(base / 'config'), 'XDG_RUNTIME_DIR': str(base / 'runtime'),
               'KEIVOTOS_HOME': str(base / 'app'), 'PYTHONPATH': str(ROOT / 'backend')}
        for name in ('DBUS_SESSION_BUS_ADDRESS', 'GNOME_KEYRING_CONTROL', 'DANBOORU_USERNAME', 'DANBOORU_API_KEY'):
            env.pop(name, None)
        subprocess.run(['dbus-run-session', '--', sys.executable, __file__, '--daemon', args.daemon,
                        '--isolated', temporary], env=env, check=True, timeout=120)


if __name__ == '__main__':
    main()
