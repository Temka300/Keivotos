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


def test_cancelled_jobs_leave_records_and_partial_files_but_not_library_cards(local):
    source,media,connect=local
    completed=jobs.create(URL,source.source_id)
    jobs.update(completed['id'],status='complete',title='Fixture complete')
    cancelled=jobs.create(URL,source.source_id)
    jobs.update(cancelled['id'],title='Fixture cancelled')
    staging=media/'.keivotos/youtube'/cancelled['id']
    staging.mkdir(parents=True)
    partial=staging/'unfinished.part'
    partial.write_bytes(b'preserved partial')
    jobs.cancel(cancelled['id'])
    failed=jobs.create(URL,source.source_id)
    jobs.update(failed['id'],status='failed',title='Fixture failed')

    page=router.library('',0,1)
    assert page['total']==2
    ids={page['items'][0]['id'],router.library('',1,1)['items'][0]['id']}
    assert ids=={failed['id'],completed['id']}
    assert router.library('cancelled',0,60)=={'items':[],'total':0}
    assert jobs.get(cancelled['id'])['status']=='cancelled'
    assert partial.read_bytes()==b'preserved partial'


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


def test_playback_diagnostics_only_accept_completed_available_jobs(local,caplog):
    from fastapi import HTTPException
    from pydantic import ValidationError
    source,media,connect=local
    job=jobs.create(URL,source.source_id)
    payload=router.YouTubePlaybackFailure(id=job['id'],reason='decode')
    with pytest.raises(HTTPException):router.playback_error(payload)
    jobs.update(job['id'],status='complete',path='YouTube/fixture.mp4')
    assert router.playback_error(payload)=={'status':'logged'}
    assert 'Playback failed' in caplog.text and job['id'] in caplog.text
    with pytest.raises(ValidationError):router.YouTubePlaybackFailure(id=job['id'],reason='arbitrary log text')
    with connect() as db:sources.update_source(db,source.source_id,visible=False)
    with pytest.raises(HTTPException):router.playback_error(payload)
    with pytest.raises(HTTPException):router.playback_error(router.YouTubePlaybackFailure(id='missing',reason='network'))


def test_retry_replaces_failed_card_and_repeated_click_returns_same_attempt(local):
    source,media,connect=local
    first=jobs.create(URL,source.source_id)
    jobs.update(first['id'],status='failed',title='Retry fixture')
    replacement=router.retry(first['id'])
    again=router.retry(first['id'])
    assert again['id']==replacement['id']
    assert router.library('Retry fixture',0,60)['total']==1
    assert [row['id'] for row in router.library('',0,60)['items']]==[replacement['id']]
    assert jobs.get(first['id'])['status']=='failed'


def test_registration_failure_keeps_published_path_for_local_retry(local,monkeypatch):
    source,media,connect=local
    first=jobs.create(URL,source.source_id)
    jobs.update(first['id'],status='downloading')
    stage=media/'.keivotos/youtube'/first['id'];stage.mkdir(parents=True)
    (stage/'video.mp4').write_bytes(b'preserved completed output')
    with monkeypatch.context() as patch:
        patch.setattr(jobs.index,'scan_source',lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('fixture index failure')))
        with pytest.raises(RuntimeError,match='fixture index failure'):
            jobs.publish(first,stage,{'path':'video.mp4','title':'Published fixture'})
    saved=jobs.get(first['id'])
    assert saved['path']==f"YouTube/{first['id']}/video.mp4"
    assert saved['failure_phase']=='integration'
    assert (media/saved['path']).read_bytes()==b'preserved completed output'


def test_additive_retry_migration_preserves_legacy_records_and_is_repeatable(tmp_path):
    original=SCHEMA.replace(" retry_of TEXT NOT NULL DEFAULT '', superseded_by TEXT NOT NULL DEFAULT '',\n failure_phase TEXT NOT NULL DEFAULT '',\n",'')
    path=tmp_path/'legacy.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript(original)
        db.execute("INSERT INTO youtube_downloads(id,url,source_id,root,video,audio,title,status,path) VALUES('old',?,'source','root','best','best','Saved','failed','YouTube/old/video.mp4')",(URL,))
        before=db.execute('SELECT * FROM youtube_downloads').fetchone()
        _publish(db);_publish(db)
        names=[column[0] for column in db.execute('SELECT * FROM youtube_downloads').description]
        after=dict(zip(names,db.execute('SELECT * FROM youtube_downloads').fetchone()))
        assert tuple(after[name] for name in names if name not in ('retry_of','superseded_by','failure_phase'))==before
        assert all(after[name]=='' for name in ('retry_of','superseded_by','failure_phase'))


def test_concurrent_retries_search_pagination_and_restart_keep_one_current_attempt(local):
    from concurrent.futures import ThreadPoolExecutor
    source,media,connect=local
    first=jobs.create(URL,source.source_id);jobs.update(first['id'],status='failed',title='100% retry fixture')
    stage=media/'.keivotos/youtube'/first['id'];stage.mkdir(parents=True)
    partial=stage/'unfinished.part';partial.write_bytes(b'preserved')
    with ThreadPoolExecutor(max_workers=6) as pool:
        replacements=list(pool.map(lambda _:router.retry(first['id']),range(12)))
    second=replacements[0]
    assert {row['id'] for row in replacements}=={second['id']}
    assert second['retry_of']==first['id'] and jobs.get(first['id'])['superseded_by']==second['id']
    jobs.recover()  # Reopen fresh DB connections; never automatically resume.
    assert jobs.get(second['id'])['status']=='interrupted'
    third=router.retry(second['id'])
    jobs.update(third['id'],status='complete')
    assert router.retry(first['id'])['id']==third['id']
    assert router.retry(second['id'])['id']==third['id']
    with connect() as db:
        for n in range(125):
            db.execute("INSERT INTO youtube_downloads(id,url,source_id,root,video,audio,title,status) VALUES(?,?,?,?,?,?,?,'complete')",
                       (f'fixture-{n:03}',URL,source.source_id,str(media),'best','best',f'Fixture {n}'))
        db.commit()
    rows=[row for offset in (0,60,120) for row in router.library('',offset,60)['items']]
    assert len(rows)==len({row['id'] for row in rows})==126
    assert not {first['id'],second['id']} & {row['id'] for row in rows}
    assert router.library('%',0,60)['total']==1
    assert router.library('%',0,60)['items'][0]['id']==third['id']
    assert partial.read_bytes()==b'preserved'


@pytest.mark.parametrize('reason',['tools','queue','source','running'])
def test_rejected_retry_keeps_original_visible_and_unlinked(local,monkeypatch,reason):
    from fastapi import HTTPException
    source,media,connect=local
    first=jobs.create(URL,source.source_id);jobs.update(first['id'],status='failed',title='Keep me')
    if reason=='tools':monkeypatch.setattr(jobs,'dependencies',lambda:{'ready':False,'missing':['fixture']})
    elif reason=='queue':
        with jobs._lock:jobs._pending.extend(['preserved-pending']*20)
    elif reason=='source':
        with connect() as db:sources.update_source(db,source.source_id,visible=False)
    else:jobs.create(URL,source.source_id)
    with pytest.raises(HTTPException):router.retry(first['id'])
    assert jobs.get(first['id'])['superseded_by']==''
    assert any(row['id']==first['id'] for row in router.library('',0,60)['items'])
    assert not list(media.iterdir())


def run_until_terminal(job_id):
    async def run():
        task=asyncio.create_task(jobs.run_queue())
        try:
            for _ in range(250):
                if jobs.get(job_id)['status'] in ('complete','failed'):return jobs.get(job_id)
                await asyncio.sleep(.02)
            pytest.fail('Local job did not finish')
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
    return asyncio.run(run())


@pytest.mark.parametrize('failure',['index','annotation'])
def test_published_file_registration_retry_never_runs_download_and_preserves_notes(local,monkeypatch,failure):
    source,media,connect=local
    first=jobs.create(URL,source.source_id)
    async def publish_fixture(job):
        stage=media/'.keivotos/youtube'/job['id'];stage.mkdir(parents=True)
        (stage/'video.mp4').write_bytes(b'preserved published bytes')
        (stage/'cover.png').write_bytes(b'preserved cover')
        jobs.publish(job,stage,{'path':'video.mp4','thumbnail':'cover.png','title':'Published fixture'})
    monkeypatch.setattr(jobs,'execute',publish_fixture)
    with monkeypatch.context() as patch:
        target=jobs.index if failure=='index' else jobs.annotations
        symbol='scan_source' if failure=='index' else 'upsert_annotation'
        def fail(*args,**kwargs):raise RuntimeError('fixture registration failure')
        patch.setattr(target,symbol,fail)
        saved=run_until_terminal(first['id'])
    assert saved['status']=='failed' and saved['failure_phase']=='integration'
    assert 'Video saved' in saved['error']
    media_path=media/saved['path'];before={p.relative_to(media):p.read_bytes() for p in media.rglob('*') if p.is_file()}
    with index.open_index(jobs.config.FILES_DB_PATH) as db:
        index.scan_source(db,source.source_id,media)
        digest=jobs.hashing.ensure_index_hash(db,media_path)
    with connect() as db:
        annotations.ensure_annotations_schema(db)
        note=annotations.upsert_annotation(db,subject_kind='file',source_id=source.source_id,relative_path=saved['path'],content_hash=digest)
        db.execute('INSERT INTO files_annotation_links(annotation_id,url,label,kind,position) VALUES(?,?,?,?,?)',
                   (note.id,'https://example.org/preserved','Existing','source',0));db.commit()
    monkeypatch.setattr(jobs,'execute',lambda *_:pytest.fail('Registration retry started a downloader'))
    monkeypatch.setattr(jobs,'dependencies',lambda:pytest.fail('Registration retry requested download tools'))
    second=router.retry(first['id']);assert second['path']==saved['path']
    # Restart between acceptance and processing, then explicitly retry the interrupted repair.
    jobs.recover();third=router.retry(second['id'])
    complete=run_until_terminal(third['id'])
    assert complete['status']=='complete' and complete['failure_phase']==''
    assert complete['path']==saved['path']
    assert {p.relative_to(media):p.read_bytes() for p in media.rglob('*') if p.is_file()}==before
    assert not (media/'YouTube'/second['id']).exists() and not (media/'YouTube'/third['id']).exists()
    with connect() as db:
        links=db.execute('SELECT url FROM files_annotation_links WHERE annotation_id=? ORDER BY position',(note.id,)).fetchall()
        assert [row['url'] for row in links]==['https://example.org/preserved',URL]
    assert router.library('Published',0,60)['total']==1


def test_legacy_published_output_reuses_only_the_original_folder(local,monkeypatch):
    source,media,connect=local
    first=jobs.create(URL,source.source_id);jobs.update(first['id'],status='failed',title='Legacy fixture')
    folder=media/'YouTube'/first['id'];folder.mkdir(parents=True)
    (folder/'video.mp4').write_bytes(b'legacy completed bytes')
    (folder/'cover.webp').write_bytes(b'legacy cover')
    monkeypatch.setattr(jobs,'execute',lambda *_:pytest.fail('Legacy published output was downloaded again'))
    second=router.retry(first['id'])
    assert second['path']==f"YouTube/{first['id']}/video.mp4"
    assert run_until_terminal(second['id'])['status']=='complete'
    assert jobs.get(first['id'])['path']=='' and jobs.get(first['id'])['status']=='failed'
    assert len(list((media/'YouTube').iterdir()))==1


@pytest.mark.parametrize('hazard',['ambiguous','empty','unsupported','symlink','nested','missing','foreign','changed-root'])
def test_unsafe_published_output_refuses_retry_without_hiding_or_deleting(local,tmp_path,hazard):
    from fastapi import HTTPException
    source,media,connect=local
    first=jobs.create(URL,source.source_id);jobs.update(first['id'],status='failed',title='Keep unsafe evidence')
    folder=media/'YouTube'/first['id'];folder.mkdir(parents=True)
    path=folder/'video.mp4';path.write_bytes(b'preserved media')
    if hazard=='ambiguous':(folder/'another.mp4').write_bytes(b'also preserved')
    elif hazard=='empty':path.write_bytes(b'')
    elif hazard=='unsupported':path.rename(folder/'original.bin')
    elif hazard=='symlink':
        external=tmp_path/'external.mp4';external.write_bytes(b'preserved external')
        path.unlink();path.symlink_to(external)
    elif hazard=='nested':
        with connect() as db:sources.register_source(db,folder)
    elif hazard=='missing':jobs.update(first['id'],path=f"YouTube/{first['id']}/missing.mp4",failure_phase='integration')
    elif hazard=='foreign':jobs.update(first['id'],path='YouTube/other-job/video.mp4',failure_phase='integration')
    elif hazard=='changed-root':
        elsewhere=tmp_path/'elsewhere';elsewhere.mkdir()
        with connect() as db:db.execute('UPDATE files_sources SET path=? WHERE source_id=?',(str(elsewhere),source.source_id));db.commit()
    before={p.relative_to(media):p.read_bytes() for p in media.rglob('*') if p.is_file()}
    with pytest.raises(HTTPException):router.retry(first['id'])
    assert jobs.get(first['id'])['superseded_by']==''
    assert router.library('',0,60)['items'][0]['id']==first['id']
    assert {p.relative_to(media):p.read_bytes() for p in media.rglob('*') if p.is_file()}==before


def test_failed_retry_is_the_only_retryable_card_then_success_replaces_it(local,monkeypatch):
    source,media,connect=local
    first=jobs.create(URL,source.source_id);jobs.update(first['id'],status='failed',title='Download retry fixture')
    async def fail(job):raise RuntimeError('fixture media download failure')
    monkeypatch.setattr(jobs,'execute',fail)
    second=router.retry(first['id']);failed=run_until_terminal(second['id'])
    assert failed['status']=='failed' and failed['failure_phase']=='download'
    assert [row['id'] for row in router.library('',0,60)['items']]==[second['id']]
    async def success(job):
        stage=media/'.keivotos/youtube'/job['id'];stage.mkdir(parents=True)
        (stage/'video.mp4').write_bytes(b'completed on third attempt')
        jobs.publish(job,stage,{'path':'video.mp4','title':'Download retry fixture'})
    monkeypatch.setattr(jobs,'execute',success)
    third=router.retry(second['id']);assert run_until_terminal(third['id'])['status']=='complete'
    assert [row['id'] for row in router.library('',0,60)['items']]==[third['id']]
    assert jobs.get(first['id'])['status']==jobs.get(second['id'])['status']=='failed'
