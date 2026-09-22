"""YouTube lifecycle with local process/engine doubles; never download remotely."""
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from files_base import sources, index, annotations
from modules.youtube import SCHEMA, _publish
from modules.youtube import jobs, engine, worker, router

URL='https://www.youtube.com/watch?v=abcdefghijk'


@pytest.fixture
def local(tmp_path,monkeypatch):
    media=tmp_path/'media';media.mkdir()
    user=tmp_path/'user.sqlite'
    @contextmanager
    def connect():
        with sqlite3.connect(user) as c:
            c.row_factory=lambda cursor,row: {column[0]:value for column,value in zip(cursor.description,row)}
            yield c
    with connect() as c:
        sources.ensure_sources_schema(c);_publish(c)
        source=sources.register_source(c,media)
    monkeypatch.setattr(jobs,'get_user_db',connect)
    monkeypatch.setattr(router,'get_user_db',connect)
    monkeypatch.setattr(jobs.config,'FILES_DB_PATH',tmp_path/'files.sqlite')
    monkeypatch.setattr(jobs.config,'SUITE_HOME',tmp_path/'home')
    monkeypatch.setattr(jobs,'dependencies',lambda:{'ready':True,'missing':[],'ffmpeg':'ffmpeg'})
    jobs.recover()
    return source,media,connect


@pytest.mark.parametrize('url',['http://youtu.be/abcdefghijk','https://youtube.com.evil/watch?v=abcdefghijk','https://youtube.com/playlist?list=abcdefghijk','https://youtube.com@localhost/watch?v=abcdefghijk','file:///etc/passwd','https://youtu.be:4433/abcdefghijk','https://youtu.be/abc'])
def test_url_validation(url):
    with pytest.raises(ValueError):engine.canonical_url(url)


def test_canonical_single_video_and_closed_qualities():
    assert engine.canonical_url('https://youtu.be/abcdefghijk?t=5')==URL
    assert engine.canonical_url('https://www.youtube.com/shorts/abcdefghijk')==URL
    assert engine.format_selector('audio','128')=='bestaudio[abr<=128]'
    assert '[height<=720]' in engine.format_selector('720','best')
    with pytest.raises(ValueError):engine.format_selector('arbitrary options','best')


def test_duplicate_cancel_retry_recovery_preserves_records(local):
    source,media,connect=local
    job=jobs.create(URL,source.source_id)
    with pytest.raises(ValueError):jobs.create(URL,source.source_id)
    jobs.cancel(job['id']);assert jobs.get(job['id'])['status']=='cancelled'
    second=jobs.create(URL,source.source_id)
    jobs.recover();assert jobs.get(second['id'])['status']=='interrupted'
    assert jobs.get(job['id'])['status']=='cancelled'
    assert not list(media.iterdir())


def test_publication_and_source_url_preserve_existing_annotations(local):
    source,media,connect=local
    job=jobs.create(URL,source.source_id);jobs.update(job['id'],status='downloading')
    staging=media/'.keivotos/youtube'/job['id'];staging.mkdir(parents=True)
    (staging/'video.mp4').write_bytes(b'completed test media')
    (staging/'cover.png').write_bytes(b'fixture thumbnail')
    jobs.publish(job,staging,{'path':'video.mp4','thumbnail':'cover.png','title':'Local result'})
    saved=jobs.get(job['id']);assert saved['status']=='complete' and saved['progress']==100
    assert (media/saved['path']).read_bytes()==b'completed test media'
    with connect() as c:
        row=c.execute('SELECT url FROM files_annotation_links').fetchone();assert row['url']==URL
    with index.open_index(jobs.config.FILES_DB_PATH) as c:
        assert c.execute('SELECT count(*) FROM files_index WHERE relative_path LIKE ?',('.keivotos%',)).fetchone()[0]==0
        assert c.execute('SELECT 1 FROM files_index WHERE relative_path=?',(saved['path'],)).fetchone()


def test_cancelled_or_moved_source_cannot_publish(local,tmp_path):
    source,media,connect=local
    job=jobs.create(URL,source.source_id)
    stage=media/'.keivotos/youtube'/job['id'];stage.mkdir(parents=True);(stage/'x.mp4').write_bytes(b'keep')
    jobs.cancel(job['id'])
    with pytest.raises(ValueError):jobs.publish(job,stage,{'path':'x.mp4','title':'x'})
    assert (stage/'x.mp4').read_bytes()==b'keep'
    jobs.update(job['id'],status='downloading')
    with connect() as c:c.execute('UPDATE files_sources SET path=? WHERE source_id=?',(str(tmp_path),source.source_id));c.commit()
    with pytest.raises(ValueError):jobs.publish(job,stage,{'path':'x.mp4','title':'x'})


def test_engine_embedding_options_and_final_event(tmp_path,monkeypatch,capsys):
    import yt_dlp
    class Engine:
        def __init__(self,options):
            self.options=options
            assert options['noplaylist'] and not options['overwrites']
            assert not options['remote_components'] and not options['cachedir']
            assert options['ffmpeg_location']=='fixture'
            assert options['js_runtimes']=={}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def extract_info(self,url,download):
            assert url==URL and download
            path=tmp_path/'video.mp4';path.write_bytes(b'finished')
            self.options['progress_hooks'][0]({'total_bytes':100,'downloaded_bytes':50,'info_dict':{'title':'Title'}})
            self.options['post_hooks'][0](str(path))
            return {'title':'Title'}
    monkeypatch.setattr(yt_dlp,'YoutubeDL',Engine)
    worker.download({'directory':str(tmp_path),'url':URL,'video':'best','audio':'best','ffmpeg':'fixture'})
    events=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0]['progress']==47.5
    assert events[-1]['event']=='complete' and events[-1]['path']=='video.mp4'


def test_actual_child_process_success_and_cancellation(local,tmp_path,monkeypatch):
    source,media,connect=local
    script=tmp_path/'app.py'
    script.write_text('''import json,sys,time
from pathlib import Path
s=json.loads(sys.stdin.readline());p=Path(s['directory'])
if s['video']=='480':
 print(json.dumps({'event':'progress','progress':10,'title':'Waiting'}),flush=True)
 time.sleep(60)
else:
 (p/'done.mp4').write_bytes(b'completed fixture')
 print(json.dumps({'event':'complete','path':'done.mp4','title':'Fixture','thumbnail':''}),flush=True)
''')
    monkeypatch.setattr(jobs.config,'CODE_ROOT',tmp_path)
    async def run():
        good=jobs.create(URL,source.source_id);jobs.update(good['id'],status='downloading')
        await jobs.execute(good)
        assert jobs.get(good['id'])['status']=='complete'
        slow=jobs.create(URL,source.source_id,'480');jobs.update(slow['id'],status='downloading')
        task=asyncio.create_task(jobs.execute(slow))
        for _ in range(100):
            if jobs.get(slow['id'])['title']=='Waiting':break
            await asyncio.sleep(.02)
        jobs.cancel(slow['id']);await asyncio.wait_for(task,5)
        assert jobs.get(slow['id'])['status']=='cancelled'
        assert not (media/'YouTube'/slow['id']).exists()
    asyncio.run(run())


def test_library_count_and_literal_search_use_named_rows(local):
    source,media,connect=local
    job=jobs.create(URL,source.source_id)
    jobs.update(job['id'],title='100% local')
    assert router.library('%',0,60)['total']==1
    assert router.library('missing',0,60)['items']==[]
    assert 'root' not in router.library('',0,60)['items'][0]


def test_background_failure_retains_partial_files_and_can_retry(local,monkeypatch,caplog):
    source,media,connect=local
    async def fail(job):
        folder=jobs.child_directory(media,['.keivotos','youtube',job['id']])
        (folder/'unfinished.part').write_bytes(b'preserved partial')
        raise RuntimeError('fixture merge failure')
    monkeypatch.setattr(jobs,'execute',fail)
    async def run():
        first=jobs.create(URL,source.source_id)
        task=asyncio.create_task(jobs.run_queue())
        try:
            for _ in range(100):
                if jobs.get(first['id'])['status']=='failed':break
                await asyncio.sleep(.02)
            assert jobs.get(first['id'])['status']=='failed'
            assert (media/'.keivotos/youtube'/first['id']/'unfinished.part').read_bytes()==b'preserved partial'
            assert jobs.create(URL,source.source_id)['id']!=first['id']
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(run())
    assert 'fixture merge failure' in caplog.text


def test_dependency_failure_refused_before_creating_files(local,tmp_path,monkeypatch):
    source,media,connect=local
    monkeypatch.setattr(jobs,'dependencies',lambda:{'ready':False,'missing':['fixture runtime']})
    with pytest.raises(ValueError,match='fixture runtime'):jobs.create(URL,source.source_id)
    assert not list(media.iterdir())


def test_default_and_custom_destinations_preserve_roles_and_media(local):
    source,media,connect=local
    assert jobs.preferences()['source_id']==''
    with pytest.raises(ValueError,match='Choose a YouTube folder'):jobs.create(URL)
    with connect() as db:sources.update_source(db,source.source_id,role='youtube')
    assert jobs.preferences()['path']==str(media)
    default=jobs.create(URL)
    assert default['source_id']==source.source_id
    custom=media.parent/'custom';custom.mkdir()
    original=custom/'keep.txt';original.write_text('preserved')
    saved=jobs.save_preferences('custom',str(custom))
    assert saved['path']==str(custom)
    job=jobs.create(URL)
    assert job['source_id']==saved['source_id']
    with connect() as db:assert sources.get_source(db,saved['source_id']).role=='files'
    jobs.save_preferences('default')
    assert jobs.preferences()['path']==str(media)
    jobs.save_preferences('custom')
    assert jobs.preferences()['path']==str(custom)
    assert original.read_text()=='preserved'
    forbidden=jobs.config.SUITE_HOME;forbidden.mkdir()
    with pytest.raises(ValueError):jobs.save_preferences('custom',str(forbidden))
    assert jobs.preferences()['path']==str(custom)
    with connect() as db:sources.update_source(db,saved['source_id'],visible=False)
    with pytest.raises(ValueError):jobs.create('https://youtu.be/lmnopqrstuv')


def test_engine_requires_only_ytdlp_and_existing_ffmpeg(monkeypatch):
    checked=[]
    def find(name):
        checked.append(name)
        return object() if name=='yt_dlp' else None
    monkeypatch.setattr(engine.importlib.util,'find_spec',find)
    monkeypatch.setattr(engine.sys,'frozen',False,raising=False)
    monkeypatch.setattr(engine.shutil,'which',lambda name: '/existing/ffmpeg' if name=='ffmpeg' else pytest.fail('Unexpected runtime lookup: '+name))
    assert engine.dependencies()=={'ready':True,'missing':[],'ffmpeg':'/existing/ffmpeg'}
    assert checked==['yt_dlp']
