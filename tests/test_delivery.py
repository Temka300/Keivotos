"""Exercise delivery declarations/specs without packaging or live user data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


@pytest.mark.parametrize('installed', [False, True])
@pytest.mark.parametrize('target', ['linux', 'win32'])
def test_specs_and_frozen_checks_with_physical_module_absence(tmp_path, installed, target):
    source = tmp_path / 'source'
    source.mkdir()
    omitted = ('__pycache__',) if installed else ('__pycache__', 'danbooru', 'youtube')
    shutil.copytree(ROOT / 'backend', source / 'backend', ignore=shutil.ignore_patterns(*omitted))
    shutil.copytree(ROOT / 'packaging', source / 'packaging')
    shutil.copy2(ROOT / 'app.py', source / 'app.py')
    shutil.copy2(ROOT / 'config.json', source / 'config.json')
    (source / 'frontend/dist').mkdir(parents=True)
    (source / 'frontend/dist/index.html').write_text('fixture')
    (source / 'scripts/release').mkdir(parents=True)
    shutil.copy2(ROOT / 'scripts/release/delivery_plan.py', source / 'scripts/release/delivery_plan.py')
    # These helper files are intentionally left present for the absent case:
    # registration, not accidental file presence, decides what to package.
    for name in ('windows_folder_picker.py', 'danbooru_gallery_dl.py'):
        (source / 'scripts' / name).touch()
    code = r'''
import json, sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import app, config
from delivery import delivery_plan
root = Path.cwd()
target, installed = sys.argv[1], sys.argv[2] == 'True'
plan = delivery_plan(target)
assert [t.name for t in plan.tools] == (['gallery-dl', 'ffmpeg'] if installed else ['ffmpeg'])
assert ('modules.danbooru.pipeline' in plan.hidden_imports) == installed
assert bool(plan.metadata_packages) == installed
assert ('yt_dlp' in plan.collect_packages) == installed
assert 'yt_dlp_ejs' not in plan.collect_packages
assert bool(plan.configured_paths) == installed
assert 'modules.danbooru.credentials' not in sys.modules
assert 'modules.danbooru.pipeline' not in sys.modules
assert 'credentials' not in sys.modules
# Evaluate the actual spec with a recording freezer API. No build is invoked.
hooks = ModuleType('PyInstaller.utils.hooks')
calls = []
def collect(name):
    calls.append(('collect', name))
    return [name]
def metadata(name, recursive):
    calls.append(('metadata', name))
    return [(name + '.dist-info', '.')]
hooks.collect_submodules, hooks.copy_metadata = collect, metadata
for name in ('PyInstaller', 'PyInstaller.utils'):
    sys.modules[name] = ModuleType(name)
sys.modules['PyInstaller.utils.hooks'] = hooks
captured = {}
def analysis(*args, **kwargs):
    captured.update(kwargs)
    return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
platform_dir = 'windows' if target == 'win32' else 'linux'
spec = root / 'packaging' / platform_dir / 'Keivotos.spec'
namespace = {'SPECPATH': str(spec.parent), 'Analysis': analysis,
             'PYZ': lambda *a, **kw: None, 'EXE': lambda *a, **kw: None,
             'COLLECT': lambda *a, **kw: None}
exec(compile(spec.read_text(), str(spec), 'exec'), namespace)
assert 'server' in captured['hiddenimports']
assert 'runtime_logging' in captured['hiddenimports']
assert ('modules.danbooru.pipeline' in captured['hiddenimports']) == installed
assert (('metadata', 'keyring') in calls) == (installed and target == 'linux')
assert (('collect', 'secretstorage') in calls) == (installed and target == 'linux')
helpers = {Path(path).name for path, _ in captured['datas']}
assert 'windows_folder_picker.py' in helpers
assert ('danbooru_gallery_dl.py' in helpers) == installed
# Keep config's source paths isolated, then simulate only frozen resource checks.
asgi_app = app._load_asgi_app()
app._load_asgi_app = lambda: asgi_app
suffix = '.exe' if target == 'win32' else ''
for tool in plan.tools:
    (root / (tool.name + suffix)).touch()
with patch.object(sys, 'platform', target), patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(root / ('Keivotos' + suffix))):
    assert app._portable_check(config) == 0
    for tool in plan.tools:
        path = root / (tool.name + suffix)
        path.unlink()
        assert app._portable_check(config) == 1
        path.touch()
    for _label, relative in plan.helpers:
        path = root / relative
        path.unlink()
        assert app._portable_check(config) == 1
        path.touch()
if not installed:
    assert not (Path(config.SUITE_HOME) / 'modules/danbooru').exists()
'''
    result = subprocess.run([sys.executable, '-c', code, target, str(installed)], cwd=source,
                            env={**os.environ, 'PYTHONPATH': str(source / 'backend'),
                                 'KEIVOTOS_HOME': str(tmp_path / 'home')},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    cli = subprocess.run([sys.executable, 'scripts/release/delivery_plan.py'], cwd=source,
                         capture_output=True, text=True, check=True, timeout=30)
    assert [t['name'] for t in json.loads(cli.stdout)['tools']] == (
        ['gallery-dl', 'ffmpeg'] if installed else ['ffmpeg'])


def test_delivery_composition_accepts_another_owner_without_configuration(monkeypatch):
    import module_registry
    from delivery import delivery_plan
    from delivery_contract import DeliveryContribution, PortableTool

    monkeypatch.setattr(module_registry, '_DELIVERY_PROVIDERS', (
        lambda target: DeliveryContribution(helpers=(('Fixture', 'scripts/fixture.py'),),
            tools=(PortableTool('fixture', '--version', 'fixture_entry.py'),)),
    ))
    plan = delivery_plan('linux')
    assert [tool.name for tool in plan.tools] == ['fixture', 'ffmpeg']
    assert plan.helpers == (('Fixture', 'scripts/fixture.py'), ('Folder picker', 'scripts/windows_folder_picker.py'))
