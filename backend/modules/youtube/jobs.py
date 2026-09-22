"""One supervised downloader process; durable records, create-only publication."""
import asyncio
from collections import deque
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid

import config
from database import get_user_db
from files_base import sources, index, annotations, hashing, serving
from maintenance import exclusive_tool_operation
from modules.youtube.engine import canonical_url, dependencies, format_selector

logger=logging.getLogger('keivotos.youtube')
_pending=deque()
_lock=threading.RLock()


def update(job_id, **values):
    allowed={'status','progress','title','path','thumbnail','error'}
    if not values or not set(values)<=allowed:raise ValueError('Invalid job fields')
    with get_user_db() as db:
        db.execute('UPDATE youtube_downloads SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),job_id))
        db.commit()


def get(job_id):
    with get_user_db() as db:
        row=db.execute('SELECT * FROM youtube_downloads WHERE id=?',(job_id,)).fetchone()
    return dict(row) if row else None


def destination(source_id, expected_root=None):
    with get_user_db() as db:source=sources.get_source(db,source_id)
    if source is None or not source.visible or source.role not in ('files','video','youtube'):
        raise ValueError('Choose a visible Files, Video or YouTube folder.')
    root=serving.resolve_within_source(source.path,'',[config.SUITE_HOME])
    if not root.is_dir() or (expected_root is not None and str(root)!=expected_root):
        raise ValueError('The destination folder changed or is unavailable.')
    return source,root


def preferences():
    with get_user_db() as db:
        row=db.execute('SELECT * FROM youtube_preferences WHERE id=1').fetchone()
        mode=row['mode'] if row else 'default'
        custom=row['custom_source'] if row else ''
        available=sources.list_sources(db,visible_only=True)
        default=next((s for s in available if s.role=='youtube'),None)
        selected=next((s for s in available if s.source_id==custom),None) if mode=='custom' else default
    return {'mode':mode,'path':selected.path if selected else '',
            'source_id':selected.source_id if selected else '',
            'default_path':default.path if default else ''}


def save_preferences(mode, path=None):
    if mode not in ('default','custom'):raise ValueError('Unknown save location mode.')
    custom=None
    if path is not None:
        reason=sources.unsafe_source_reason(path,[config.SUITE_HOME])
        if reason:raise ValueError(reason)
        with get_user_db() as db:
            existing=next((s for s in sources.list_sources(db) if Path(s.path).resolve()==Path(path).expanduser().resolve()),None)
            if existing and (not existing.visible or existing.role not in ('files','video','youtube')):
                raise ValueError('Choose a visible Files, Video or YouTube folder.')
            custom=(existing or sources.register_source(db,path)).source_id
    with get_user_db() as db:
        db.execute("INSERT OR IGNORE INTO youtube_preferences(id) VALUES(1)")
        db.execute('UPDATE youtube_preferences SET mode=? WHERE id=1',(mode,))
        if custom is not None:db.execute('UPDATE youtube_preferences SET custom_source=? WHERE id=1',(custom,))
        db.commit()
    return preferences()


def create(url,source_id=None,video='best',audio='best'):
    if source_id is None:
        source_id=preferences()['source_id']
        if not source_id:raise ValueError('Choose a YouTube folder in Files, or a custom save location in YouTube settings.')
    url=canonical_url(url);format_selector(video,audio)
    tools=dependencies()
    if not tools['ready']:raise ValueError('Missing: '+', '.join(tools['missing']))
    _,root=destination(source_id)
    with _lock, get_user_db() as db:
        if db.execute("SELECT 1 FROM youtube_downloads WHERE url=? AND source_id=? AND video=? AND audio=? AND status IN ('queued','downloading','merging')",(url,source_id,video,audio)).fetchone():
            raise ValueError('This download is already running.')
        if len(_pending)>=20:raise ValueError('The download queue is full.')
        job_id=uuid.uuid4().hex
        db.execute('INSERT INTO youtube_downloads(id,url,source_id,root,video,audio) VALUES(?,?,?,?,?,?)',(job_id,url,source_id,str(root),video,audio));db.commit()
        _pending.append(job_id)
    logger.info('Download queued: job=%s url=%s destination=%s',job_id,url,root)
    return get(job_id)


def cancel(job_id):
    with _lock:
        item=get(job_id)
        if not item:raise ValueError('Download not found.')
        if item['status'] in ('queued','downloading','merging'):
            update(job_id,status='cancelled')
            logger.info('Download cancelled: job=%s',job_id)
    return get(job_id)


def recover():
    with _lock, get_user_db() as db:
        _pending.clear()
        db.execute("UPDATE youtube_downloads SET status='interrupted',error='Interrupted. Retry to download again.' WHERE status IN ('queued','downloading','merging')")
        db.commit()


def child_directory(root,parts):
    current=root
    for part in parts:
        current=current/part
        if current.is_symlink():raise ValueError('Destination contains a symbolic link.')
        current.mkdir(exist_ok=True)
        if current.resolve()!=current:raise ValueError('Destination changed.')
    return current


def publish(job, staging, result):
    with exclusive_tool_operation('finishing a YouTube download',wait=False), _lock:
        current=get(job['id'])
        if not current or current['status'] not in ('downloading','merging'):
            raise ValueError('Download was cancelled or its record changed.')
        source,root=destination(job['source_id'],job['root'])
        expected=root/'.keivotos'/'youtube'/job['id']
        if staging!=expected or staging.resolve()!=expected:raise ValueError('Staging location changed.')
        name=result['path'];thumbnail=result.get('thumbnail','')
        for item in [name]+([thumbnail] if thumbnail else []):
            if Path(item).name!=item or '/' in item or '\\' in item or not (staging/item).is_file() or (staging/item).is_symlink():
                raise ValueError('Invalid completed output')
        final=child_directory(root,['YouTube'])/job['id']
        if final.exists():raise ValueError('Output already exists; refusing to replace it.')
        with get_user_db() as db:other_roots=[Path(s.path).resolve() for s in sources.list_sources(db) if s.source_id!=source.source_id]
        if any(other.is_relative_to(root) and final.is_relative_to(other) for other in other_roots):
            raise ValueError('Choose the nested destination source directly.')
        staging.rename(final)
        relative=(final/name).relative_to(root).as_posix()
        # Register only after yt-dlp's successful final move/merge. Preserve output
        # if indexing/annotation fails; a failed integration never deletes media.
        with index.open_index(config.FILES_DB_PATH) as db:
            index.scan_source(db,source.source_id,root,excluded_roots=[config.SUITE_HOME,*other_roots])
            digest=hashing.ensure_index_hash(db,final/name)
        if not digest:raise ValueError('Could not identify completed media.')
        with get_user_db() as db:
            annotations.ensure_annotations_schema(db)
            note=annotations.upsert_annotation(db,subject_kind='file',source_id=source.source_id,relative_path=relative,content_hash=digest)
            links=annotations.list_links(db,note.id)
            if not any(link.url==job['url'] for link in links):
                db.execute('INSERT INTO files_annotation_links(annotation_id,url,label,kind,position) VALUES(?,?,?,?,?)',(note.id,job['url'],'YouTube','source',len(links)));db.commit()
        update(job['id'],status='complete',progress=100,title=result['title'],path=relative,thumbnail=(final/thumbnail).relative_to(root).as_posix() if thumbnail else '',error='')
        logger.info('Download complete: job=%s file=%s',job['id'],final/name)


async def terminate(process):
    if process.returncode is not None:return
    if sys.platform=='win32':
        killer=await asyncio.create_subprocess_exec('taskkill','/PID',str(process.pid),'/T','/F',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
    else:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    await process.wait()


async def execute(job):
    _,root=destination(job['source_id'],job['root'])
    parent=child_directory(root,['.keivotos','youtube'])
    staging=parent/job['id'];staging.mkdir(exist_ok=False)
    tools=dependencies()
    if not tools['ready']:raise ValueError('Missing: '+', '.join(tools['missing']))
    command=([sys.executable,'--youtube-worker'] if getattr(sys,'frozen',False)
             else [sys.executable,str(config.CODE_ROOT/'app.py'),'--youtube-worker'])
    launch=asyncio.create_task(asyncio.create_subprocess_exec(*command,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,
        **({'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform=='win32' else {'start_new_session':True})))
    try:process=await asyncio.shield(launch)
    except asyncio.CancelledError:
        process=await launch;await terminate(process);raise
    result=None
    async def events():
        nonlocal result
        while line:=await process.stdout.readline():
            event=json.loads(line)
            if event.get('event')=='complete':result=event
            elif get(job['id']) and get(job['id'])['status'] not in ('cancelled','interrupted'):
                if event.get('event')=='progress':
                    update(job['id'],progress=max(get(job['id'])['progress'],min(95,float(event['progress']))),title=str(event['title'])[:512])
                elif event.get('event')=='merging':update(job['id'],status='merging')
    async def diagnostics():
        while line:=await process.stderr.readline():logger.info('job=%s %s',job['id'],line.decode('utf-8','replace').strip()[:2000])
    tasks=[]
    try:
        process.stdin.write(json.dumps({**job,'directory':str(staging),'ffmpeg':tools['ffmpeg']}).encode()+b'\n')
        await process.stdin.drain();process.stdin.close()
        tasks=[asyncio.create_task(events()),asyncio.create_task(diagnostics())]
        while process.returncode is None:
            item=get(job['id'])
            if not item or item['status']=='cancelled':await terminate(process);return
            if any(t.done() and t.exception() for t in tasks):raise RuntimeError('Downloader event stream failed')
            await asyncio.sleep(.2)
        await asyncio.gather(*tasks)
        if process.returncode or not result:raise RuntimeError('Download failed. See Logs.')
        completion=asyncio.create_task(asyncio.to_thread(publish,job,staging,result))
        try:await asyncio.shield(completion)
        except asyncio.CancelledError:await completion;raise
    finally:
        await terminate(process)
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)


async def run_queue():
    active=None
    try:
        while True:
            with _lock:job_id=_pending.popleft() if _pending else None
            if job_id:
                active=get(job_id)
                if not active or active['status']!='queued':active=None;continue
                update(job_id,status='downloading');logger.info('Download started: job=%s',job_id)
                try:await execute(active)
                except asyncio.CancelledError:raise
                except Exception:
                    logger.exception('Download failed: job=%s; any partial/completed files are retained',job_id)
                    if get(job_id) and get(job_id)['status']!='cancelled':update(job_id,status='failed',error='Download failed. See Logs.')
                active=None
            else:await asyncio.sleep(.2)
    finally:
        # Disable/shutdown never resumes remote work automatically on re-enable.
        recover()
        logger.info('YouTube worker stopped; unfinished downloads marked interrupted')
