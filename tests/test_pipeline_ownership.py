"""Compatibility entry points and offline end-to-end pipeline ownership checks."""
from __future__ import annotations

import ast
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))
from modules.danbooru import pipeline


class PipelineOwnershipTests(unittest.TestCase):
    def test_historical_imports_are_the_owner_including_mutable_globals(self):
        for name in ('danbooru_gallery_dl', 'scripts.danbooru_gallery_dl'):
            with self.subTest(name=name):
                legacy = importlib.import_module(name)
                self.assertIs(legacy, pipeline)
                roots = []
                with patch.object(legacy, '_LIBRARY_ROOTS', roots):
                    self.assertIs(pipeline._LIBRARY_ROOTS, roots)
                with patch.object(legacy, 'run_sync', return_value=73) as sync:
                    args = pipeline.build_parser().parse_args(['sync'])
                    self.assertEqual(args.func(args), 73)
                    sync.assert_called_once_with(args)

    def test_source_and_frozen_resource_defaults_preserve_the_script_root(self):
        self.assertEqual(pipeline.project_root(), ROOT)
        self.assertEqual(pipeline.BACKEND_DIR, ROOT / 'backend')
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary)
            with patch.object(sys, '_MEIPASS', str(bundle), create=True), patch.object(
                pipeline, '__file__', str(bundle / 'modules/danbooru/pipeline.py')
            ):
                args = pipeline.build_parser().parse_args(['sync'])
                self.assertEqual(args.root, bundle)
                self.assertEqual(args.sidecar_dir, bundle / 'data/sidecars')
                self.assertEqual(args.user_db, bundle / 'data/user.sqlite')
                self.assertEqual(args.gallery_dl_dir, bundle / '_gallery-dl')
                self.assertEqual(pipeline.resolve_project_path(Path('relative')), bundle / 'relative')

    def test_cli_help_and_errors_match_the_pre_move_capture_from_another_cwd(self):
        cases = json.loads((ROOT / 'tests/snapshots/pipeline_cli.json').read_text())
        with tempfile.TemporaryDirectory() as temporary:
            env = {**os.environ, 'COLUMNS': '80', 'KEIVOTOS_HOME': temporary}
            for case in cases:
                with self.subTest(args=case['args']):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / 'scripts/danbooru_gallery_dl.py'), *case['args']],
                        cwd=temporary, env=env, text=True, capture_output=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, case['returncode'])
                    self.assertEqual(result.stdout, case['stdout'])
                    self.assertEqual(result.stderr, case['stderr'])
            self.assertEqual(list(Path(temporary).iterdir()), [], 'help/import must not initialize a home')

    def test_packaged_helper_dispatch_reaches_owner_and_propagates_status(self):
        import app
        with patch.object(sys, 'argv', ['app.py']), patch.object(pipeline, 'main', return_value=19) as main:
            self.assertEqual(app._run_helper('danbooru_gallery_dl.py', ['sync']), 19)
            main.assert_called_once_with()
            self.assertEqual(sys.argv[1:], ['sync'])
        with patch.object(sys, 'argv', ['app.py']), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(app._run_helper('danbooru_gallery_dl.py', ['--help']), 0)
            self.assertIn('import-discover', output.getvalue())

    def test_both_freezers_include_the_owner_imported_by_the_data_only_wrapper(self):
        from delivery import delivery_plan
        for platform in ('win32', 'linux'):
            self.assertIn('modules.danbooru.pipeline', delivery_plan(platform).hidden_imports)

    def test_legacy_cli_runs_local_phases_and_is_resumable_without_touching_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            library = base / 'media'
            library.mkdir()
            media = library / 'sample.png'
            Image.new('RGB', (40, 30), (10, 20, 30)).save(media)
            original = media.read_bytes()
            database = base / 'index.sqlite'
            command = [sys.executable, str(ROOT / 'scripts/danbooru_gallery_dl.py'),
                       '--root', str(base), '--sidecar-dir', str(base / 'sidecars'),
                       '--user-db', str(base / 'user.sqlite')]
            env = {**os.environ, 'KEIVOTOS_HOME': str(base / 'home')}
            for phase in ('import-discover', 'import-enrich', 'import-finalize', 'import-finalize'):
                result = subprocess.run(command + [phase, str(library), '--output', str(database)],
                                        cwd=base, env=env, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            with sqlite3.connect(database) as db:
                row = db.execute('SELECT f.local_md5,p.width,p.height FROM files f JOIN posts p ON p.file_id=f.id').fetchone()
                self.assertEqual(row, (hashlib.md5(original).hexdigest(), 40, 30))
                self.assertEqual(db.execute('SELECT phase,status FROM ingest_state').fetchone(), ('finalized', 'done'))
                self.assertEqual(db.execute('SELECT count(*) FROM files').fetchone()[0], 1)
            self.assertEqual(media.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
