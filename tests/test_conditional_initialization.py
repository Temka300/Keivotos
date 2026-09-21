"""Real isolated startup with enabled, disabled and physically absent Danbooru."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r'''
import asyncio, json, sqlite3
from pathlib import Path
import config, database, lifecycle
from server import app
from routers import files, user_settings, suite
mode = __import__('os').environ['FIXTURE_MODE']
if mode == 'enabled':
    database.init_user_db(set())
    with database.get_user_db() as conn:
        import suite_modules
        suite_modules.ensure_schema(conn)
        suite_modules.set_enabled(conn, 'danbooru', True)
if mode == 'preserved':
    database.init_data_db()
    database.init_user_db()
    with database.get_data_db() as conn:
        conn.execute("INSERT INTO files(id,path,name) VALUES(1,'/fixture/one.jpg','one.jpg')")
        conn.execute("INSERT INTO posts(id,file_id,rating) VALUES(1,1,NULL)")
        conn.commit()
    with database.get_user_db() as conn:
        conn.execute("INSERT INTO favorites(file_id,added_at) VALUES(1,'2001-01-01')")
        conn.commit()
async def run():
    async with lifecycle.lifespan(None):
        assert not any(t.get_name()=='suite-recovery-checkpoint' for t in asyncio.all_tasks())
        import local_recovery
        recovery = local_recovery.local_recovery_status()
        assert Path(recovery['directory']) == config.SUITE_HOME / 'local_recovery' / 'user_database'
        assert recovery['count'] == 0
        assert recovery['enabled'] is False
        if mode in {'disabled', 'absent'}:
            assert not config.MODULE_HOME.exists()
        assert files.list_sources() == []
        assert user_settings.get_user_setting('profile_name').value == 'Keivotos'
        if mode == 'absent':
            assert [m.id for m in suite.list_modules()] == ['files']
            assert '/api/stats' not in app.openapi()['paths']
            assert '/api/video/library' not in app.openapi()['paths']
            assert '/api/manga/library' not in app.openapi()['paths']
        import backup_bundle, zipfile
        created = backup_bundle.create_backup_bundle()
        manifest = backup_bundle.inspect_backup_bundle(Path(created['path']))
        with zipfile.ZipFile(created['path']) as archive:
            assert 'databases/user.sqlite' in archive.namelist()
        assert manifest['component_owners']['user_database'] == 'suite'
        assert manifest['component_owners']['file_attachments'] == 'files'
        if mode in {'disabled', 'absent'}:
            assert not config.MODULE_HOME.exists()
            assert not manifest['components'].get('library_database', False)
        if mode == 'preserved':
            assert manifest['components']['library_database']
        tasks = sorted(t.get_name() for t in asyncio.all_tasks() if t.get_name().startswith('danbooru-'))
    with database.get_user_db() as conn:
        tables = sorted(row['name'] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        favorite = conn.execute('SELECT added_at FROM favorites').fetchone() if mode=='preserved' else None
    result = {'tables':tables,'tasks':tasks,'index':config.DATA_DB_PATH.exists(),'favorite':favorite}
    if mode=='preserved':
        with database.get_data_db() as conn: result['rating']=conn.execute('SELECT rating FROM posts').fetchone()['rating']
    print(json.dumps(result))
asyncio.run(run())
'''


class ConditionalInitializationTests(unittest.TestCase):
    def run_fixture(self, mode):
        with tempfile.TemporaryDirectory(prefix='keivotos-init-') as temp:
            root = Path(temp)
            backend = ROOT / 'backend'
            if mode == 'absent':
                backend = root / 'backend'
                shutil.copytree(ROOT/'backend', backend, ignore=shutil.ignore_patterns('__pycache__','*.pyc','video','manga'))
                # Only the disposable copy is omitted; repository and user data are untouched.
                shutil.rmtree(backend/'modules/danbooru')
            home = root/'home'
            home.mkdir()
            (home/'config.json').write_text(json.dumps({'default_library_created':True,'automation_enabled':False}))
            result = subprocess.run([sys.executable,'-c',SCRIPT],cwd=root,
                env={**os.environ,'PYTHONPATH':str(backend),'KEIVOTOS_HOME':str(home),'FIXTURE_MODE':mode},
                capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertNotIn('Traceback',result.stderr)
            self.assertNotIn('failed',result.stderr.lower())
            return json.loads(result.stdout)

    def test_disabled_starts_suite_without_index_or_module_tables(self):
        result=self.run_fixture('disabled')
        self.assertFalse(result['index'])
        self.assertEqual(result['tasks'],[])
        self.assertIn('user_settings',result['tables'])
        self.assertNotIn('favorites',result['tables'])

    def test_enabled_initializes_index_tables_and_workers(self):
        result=self.run_fixture('enabled')
        self.assertTrue(result['index'])
        self.assertIn('favorites',result['tables'])
        self.assertIn('danbooru-auto-ingest',result['tasks'])

    def test_disabled_existing_records_are_not_migrated(self):
        result=self.run_fixture('preserved')
        self.assertTrue(result['index'])
        self.assertEqual(result['tasks'],[])
        self.assertIsNone(result['rating'])
        self.assertEqual(result['favorite'],{'added_at':'2001-01-01'})

    def test_physically_absent_module_starts_suite(self):
        result=self.run_fixture('absent')
        self.assertFalse(result['index'])
        self.assertNotIn('favorites',result['tables'])
        self.assertEqual(result['tasks'],[])
