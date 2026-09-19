"""Owner identity and helper dispatch without real credentials or app startup."""
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT))


def test_legacy_credentials_are_the_owner_and_callers_share_functions(monkeypatch):
    from modules.danbooru import credentials, client, tools
    from modules.danbooru.routers import tools as routes

    assert importlib.import_module('credentials') is credentials
    assert client.effective_credentials is credentials.effective_credentials
    assert tools.credential_environment is credentials.credential_environment
    for name in ('clear_credentials', 'credential_environment', 'credentials_status',
                 'effective_credentials', 'save_credentials'):
        assert getattr(routes, name) is getattr(credentials, name)
    monkeypatch.delenv('DANBOORU_USERNAME', raising=False)
    monkeypatch.delenv('DANBOORU_API_KEY', raising=False)
    legacy = importlib.import_module('credentials')
    monkeypatch.setattr(legacy, 'saved_credentials', lambda: ('fixture-user', 'fixture-key'))
    assert client.effective_credentials() == ('fixture-user', 'fixture-key', 'saved')
    assert legacy._credential_lock is credentials._credential_lock
    assert credentials._logger.name == 'credentials'


@pytest.mark.parametrize('result', [0, 2, 19])
def test_pipeline_dispatch_preserves_order_arguments_and_exit_status(monkeypatch, result):
    import app

    calls = []
    monkeypatch.setattr(app, '_load_configuration', lambda **kw: calls.append(('config', kw)))
    def run(name, arguments):
        calls.append((name, arguments))
        return result
    monkeypatch.setattr(app, '_run_helper', run)
    monkeypatch.setattr(app, '_load_asgi_app', Mock(side_effect=AssertionError('server started')))
    assert app.main(['--pipeline', 'sync', '--root', 'path with spaces']) == result
    assert calls == [('config', {'migrate_legacy_home': True}),
                     ('danbooru_gallery_dl.py', ['sync', '--root', 'path with spaces'])]


def test_worker_requires_exact_arguments_and_unclaimed_commands_have_no_effect():
    from modules.danbooru.helpers import dispatch_helper

    config = Mock(side_effect=AssertionError('configuration loaded'))
    runner = Mock(side_effect=AssertionError('script executed'))
    for arguments in ([], ['--version'], ['--folder-picker'], ['--credential-worker', 'extra']):
        assert dispatch_helper(arguments, load_configuration=config, run_helper=runner) is None
    config.assert_not_called()
    runner.assert_not_called()


def test_registry_can_dispatch_another_owner_and_stops_on_zero(monkeypatch):
    import module_registry

    first = Mock(return_value=None)
    second = Mock(return_value=0)
    third = Mock(side_effect=AssertionError('dispatch continued after success'))
    monkeypatch.setattr(module_registry, '_HELPER_HANDLERS', (first, second, third))
    config, runner = Mock(), Mock()
    assert module_registry.dispatch_helper(['--fixture'], load_configuration=config, run_helper=runner) == 0
    second.assert_called_once_with(['--fixture'], load_configuration=config, run_helper=runner)
    third.assert_not_called()


@pytest.mark.parametrize('installed', [False, True])
def test_launcher_and_folder_picker_need_no_credential_imports(tmp_path, installed):
    # Physically omit the optional module from a copied source tree; never
    # rename the real checkout or touch live configuration/credential files.
    source = tmp_path / 'source'
    source.mkdir()
    shutil.copy2(ROOT / 'app.py', source / 'app.py')
    omitted = ('__pycache__',) if installed else ('__pycache__', 'danbooru')
    shutil.copytree(ROOT / 'backend', source / 'backend', ignore=shutil.ignore_patterns(*omitted))
    code = '''
import sys
from unittest.mock import Mock
import app, module_registry
app._load_configuration = Mock(side_effect=AssertionError('configuration loaded'))
app._load_asgi_app = Mock(side_effect=AssertionError('server started'))
app._run_helper = Mock(return_value=23)
assert app.main(['--folder-picker', '--fixture']) == 23
app._run_helper.assert_called_once_with('windows_folder_picker.py', ['--fixture'])
assert 'credentials' not in sys.modules
assert 'modules.danbooru.credentials' not in sys.modules
assert 'modules.danbooru.pipeline' not in sys.modules
assert 'config' not in sys.modules
if not module_registry._HELPER_HANDLERS:
    for flag in ('--pipeline', '--credential-worker'):
        try:
            app.main([flag])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError('absent module command accepted')
    assert not any(name.startswith('modules.danbooru') for name in sys.modules)
'''
    home = tmp_path / 'home'
    result = subprocess.run([sys.executable, '-c', code], cwd=source,
                            env={**os.environ, 'PYTHONPATH': str(source / 'backend'),
                                 'KEIVOTOS_HOME': str(home)},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not home.exists()


def test_worker_dispatch_preserves_main_namespace_without_config_loader(monkeypatch, capsys):
    import app
    from modules.danbooru import credentials

    monkeypatch.setattr(credentials, '_VAULT_WORKER', "assert __name__ == '__main__'; print('fixture-worker')")
    monkeypatch.setattr(app, '_load_configuration', Mock(side_effect=AssertionError('configuration loaded')))
    monkeypatch.setattr(app, '_run_helper', Mock(side_effect=AssertionError('script executed')))
    assert app.main(['--credential-worker']) == 0
    assert capsys.readouterr().out == 'fixture-worker\n'
