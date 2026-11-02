"""Real isolated image/ZIP fixtures: order, preservation and rejected reads."""
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import asyncio
import os
import sqlite3
import stat
import subprocess
import sys
import time
import zipfile
from urllib.parse import urlencode

import pytest
from PIL import Image
from fastapi import FastAPI, HTTPException
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import database
import thumbnails
from files_base import sources, index
from modules import manga
from modules.manga import library as engine, router
from modules.manga import page_cache
from modules.manga.page_cache import ManifestCache, PageData, ResponseCache


@pytest.fixture(autouse=True)
def fresh_manifests():
    engine.manifests.clear()
    engine.responses.clear()
    yield
    engine.manifests.clear()
    engine.responses.clear()


def picture(color='white'):
    data=BytesIO()
    Image.new('RGB',(60,90),color).save(data,'PNG')
    return data.getvalue()


@pytest.fixture
def library(tmp_path,monkeypatch):
    media=tmp_path/'media';media.mkdir()
    folder=media/'Story'/'Chapter 2';folder.mkdir(parents=True)
    for name in ['10.png','2.png','1.png']:(folder/name).write_bytes(picture())
    with zipfile.ZipFile(media/'Story'/'Chapter 10.cbz','w') as z:
        for name in ['10.png','2.png','1.png']:z.writestr(name,picture())
    user=tmp_path/'user.sqlite'
    @contextmanager
    def connect():
        with sqlite3.connect(user) as connection:
            connection.row_factory=sqlite3.Row
            yield connection
    with connect() as connection:
        sources.ensure_sources_schema(connection)
        source=sources.register_source(connection,media)
    db=tmp_path/'files.sqlite'
    with index.open_index(db) as connection:index.scan_source(connection,source.source_id,media)
    monkeypatch.setattr(router,'get_user_db',connect)
    monkeypatch.setattr(database,'get_user_db',connect)
    monkeypatch.setattr(router.config,'FILES_DB_PATH',db)
    monkeypatch.setattr(router.config,'SUITE_HOME',tmp_path/'home')
    monkeypatch.setattr(thumbnails,'THUMB_DIR',tmp_path/'cache')
    monkeypatch.setattr(thumbnails,'get_thumbnail_cache_limit_bytes',lambda:64*1024*1024)
    return source,connect,media,db


def test_discovery_natural_order_folder_archive_read_and_preservation(library):
    source,connect,media,db=library
    assert router.library('',0,60)['total']==0
    manga.adopt(source.source_id)
    item=router.library('story',0,60)['items'][0]
    assert item['name']=='Story'
    chapters=router.chapters(source.source_id,'Story')['items']
    assert [c['name'] for c in chapters]==['Chapter 2','Chapter 10']
    assert [Path(p).name for p in engine.folder_pages(db,source.source_id,'Story/Chapter 2')]==['1.png','2.png','10.png']
    for chapter in chapters:
        assert router.pages(source.source_id,chapter['path'],chapter['kind'])=={'count':3}
        response=router.page(source.source_id,chapter['path'],chapter['kind'],0,False)
        assert response.media_type=='image/webp'
        assert Image.open(BytesIO(response.body)).size==(60,90)
    before={str(p):p.read_bytes() for p in media.rglob('*') if p.is_file()}
    manga.release(source.source_id)
    assert router.library('',0,60)['total']==0
    manga.adopt(source.source_id);manga.release(source.source_id,True)
    assert before=={str(p):p.read_bytes() for p in media.rglob('*') if p.is_file()}
    descriptor=manga.descriptor(media,'test')
    assert not descriptor.backup_components() and not descriptor.background_tasks()


def test_missing_hidden_and_traversal_rejected(library):
    source,connect,media,db=library;manga.adopt(source.source_id)
    for path in ['../secret','/etc','Story/missing']:
        with pytest.raises(HTTPException):router.pages(source.source_id,path,'folder')
    router.page(source.source_id,'Story/Chapter 2','folder',0,False)
    router.page(source.source_id,'Story/Chapter 10.cbz','archive',0,False)
    with connect() as c:sources.update_source(c,source.source_id,visible=False)
    with pytest.raises(HTTPException):router.page(source.source_id,'Story/Chapter 2','folder',0,False)
    with pytest.raises(HTTPException):router.page(source.source_id,'Story/Chapter 10.cbz','archive',0,False)


@pytest.mark.parametrize('name',['../page.png','/page.png','C:/page.png','C:page.png','a\\page.png','a/./page.png','a//page.png'])
def test_hostile_archive_names(tmp_path,name):
    path=tmp_path/'bad.cbz'
    stored_name='a/page.png' if name=='a\\page.png' else name
    with zipfile.ZipFile(path,'w') as z:z.writestr(stored_name,picture())
    if name=='a\\page.png':
        raw=path.read_bytes()
        assert raw.count(b'a/page.png')==2
        path.write_bytes(raw.replace(b'a/page.png',b'a\\page.png'))
    with pytest.raises(ValueError):
        with engine.open_archive(path):pass



def test_raw_backslash_rejected_after_windows_name_normalization(tmp_path,monkeypatch):
    path=tmp_path/'windows.cbz'
    with zipfile.ZipFile(path,'w') as z:z.writestr('a/page.png',picture())
    path.write_bytes(path.read_bytes().replace(b'a/page.png',b'a\\page.png'))
    original=zipfile.ZipInfo
    class WindowsZipInfo(original):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.filename=self.filename.replace('\\','/')
    monkeypatch.setattr(zipfile,'ZipInfo',WindowsZipInfo)
    with zipfile.ZipFile(path) as archive:
        info=archive.infolist()[0]
        assert info.filename=='a/page.png'
        assert info.orig_filename=='a\\page.png'
    with pytest.raises(ValueError,match='Unsafe'):
        with engine.open_archive(path):pass


def test_symlinks_duplicates_and_expansion_limits(tmp_path):
    for kind in ['symlink','duplicate','expansion']:
        path=tmp_path/(kind+'.zip')
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
            if kind=='symlink':
                info=zipfile.ZipInfo('page.png');info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,b'elsewhere')
            elif kind=='duplicate':z.writestr('a.png',picture());z.writestr('A.png',picture())
            else:z.writestr('a.png',b'0'*2_000_000)
        with pytest.raises(ValueError):
            with engine.open_archive(path):pass


def test_outside_and_protected_symlink_pages_logged(library,tmp_path,caplog):
    source,connect,media,db=library;manga.adopt(source.source_id)
    router.page(source.source_id,'Story/Chapter 2','folder',0,False)
    outside=tmp_path/'outside.png';outside.write_bytes(picture())
    first=media/'Story/Chapter 2/1.png';first.unlink();first.symlink_to(outside)
    with pytest.raises(HTTPException) as caught:router.page(source.source_id,'Story/Chapter 2','folder',0,False)
    assert caught.value.status_code==403
    assert 'Manga read failed' in caplog.text
    home=router.config.SUITE_HOME;home.mkdir();secret=home/'secret.png';secret.write_bytes(picture())
    first.unlink();first.symlink_to(secret)
    with pytest.raises(HTTPException):router.page(source.source_id,'Story/Chapter 2','folder',0,False)


def test_corrupt_image_and_page_bounds(library,caplog):
    source,connect,media,db=library;manga.adopt(source.source_id)
    (media/'Story/Chapter 2/1.png').write_bytes(b'not an image')
    for n in [0,999]:
        with pytest.raises(HTTPException):router.page(source.source_id,'Story/Chapter 2','folder',n,False)
    assert 'See Logs' in str(caplog.text) or 'Manga read failed' in caplog.text


def test_directory_bounds_before_zipfile_allocation(tmp_path,monkeypatch):
    path=tmp_path/'many.zip'
    with zipfile.ZipFile(path,'w') as z:
        for n in range(3):z.writestr(str(n)+'.png',picture())
    monkeypatch.setattr(engine,'MAX_ENTRIES',2)
    with pytest.raises(ValueError):
        with engine.open_archive(path):pass
    monkeypatch.setattr(engine,'MAX_PIXELS',100)
    with pytest.raises(ValueError):engine.render_page(picture())


def test_source_root_chapters_literal_search_and_pagination(library):
    source,connect,media,db=library
    (media/'root.png').write_bytes(picture())
    special=media/'100%';special.mkdir();(special/'1.png').write_bytes(picture())
    with index.open_index(db) as c:index.scan_source(c,source.source_id,media)
    manga.adopt(source.source_id)
    assert router.library('%',0,60)['items'][0]['name']=='100%'
    assert router.library('',0,1)['total']==3
    assert len(router.library('',1,1)['items'])==1
    assert router.pages(source.source_id,'','folder')['count']==1


def test_unbounded_compression_methods_refused(tmp_path):
    path=tmp_path/'lzma.zip'
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_LZMA) as z:z.writestr('1.png',picture())
    with pytest.raises(ValueError):
        with engine.open_archive(path):pass


def test_archive_manifest_reuse_and_closed_handles(library, monkeypatch):
    source,connect,media,db=library;manga.adopt(source.source_id)
    validate=engine._validate_archive
    calls=[]
    def counted(archive):
        calls.append(archive.filename)
        return validate(archive)
    monkeypatch.setattr(engine,'_validate_archive',counted)
    chapter='Story/Chapter 10.cbz'
    assert router.pages(source.source_id,chapter,'archive')=={'count':3}
    for number in [0,1,0]:
        assert Image.open(BytesIO(router.page(source.source_id,chapter,'archive',number,False).body)).size==(60,90)
    assert len(calls)==1
    # This also exercises the native Windows handle rule when run on Windows.
    target=media/chapter; renamed=target.with_suffix('.moved')
    target.rename(renamed);renamed.rename(target)
    assert router.pages(source.source_id,chapter,'archive')=={'count':3}
    with connect() as connection:sources.update_source(connection,source.source_id,role='files')
    with pytest.raises(HTTPException):router.page(source.source_id,chapter,'archive',0,False)


def test_cached_archive_changed_directory_with_restored_time_revalidates(library, monkeypatch):
    source,connect,media,db=library
    path=media/'Story/Chapter 10.cbz'
    # Emulate a filesystem whose change timestamp cannot distinguish an
    # in-place rewrite. The directory digest must still invalidate validation.
    monkeypatch.setattr(engine,'file_identity',lambda info:(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns))
    with engine.open_archive(path,source_id=source.source_id) as (_,pages):
        assert [info.filename for info in pages]==['1.png','2.png','10.png']
    stamp=path.stat()
    original=path.read_bytes()
    path.write_bytes(original.replace(b'1.png',b'4.png'))
    os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    with engine.open_archive(path,source_id=source.source_id) as (_,pages):
        assert [info.filename for info in pages]==['2.png','4.png','10.png']
    path.write_bytes(original.replace(b'1.png',b'/.png'))
    os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    with pytest.raises(ValueError,match='Unsafe'):
        with engine.open_archive(path,source_id=source.source_id):pass


def test_cached_archive_still_bounds_directory_before_parsing(library,monkeypatch):
    source,connect,media,db=library
    path=media/'Story/Chapter 10.cbz'
    with engine.open_archive(path,source_id=source.source_id):pass
    monkeypatch.setattr(engine,'MAX_ENTRIES',2)
    def forbidden(*args,**kwargs):raise AssertionError('Oversized directory was parsed')
    monkeypatch.setattr(engine.zipfile,'ZipFile',forbidden)
    with pytest.raises(ValueError,match='directory'):
        with engine.open_archive(path,source_id=source.source_id):pass


def test_mutation_during_archive_read_refuses_result(library):
    source,connect,media,db=library
    path=media/'Story/Chapter 10.cbz'
    with pytest.raises(ValueError,match='changed'):
        with engine.open_archive(path,source_id=source.source_id) as (archive,pages):
            assert archive.read(pages[0])==picture()
            path.write_bytes(path.read_bytes()+b'changed')
    # No still-open ZipFile is retained by a rejected manifest.
    path.rename(path.with_suffix('.moved'))


def test_parallel_cached_reads_are_independent_and_preserve_original(library):
    source,connect,media,db=library
    path=media/'Story/Chapter 10.cbz';before=path.read_bytes()
    def read(number):
        with engine.open_archive(path,source_id=source.source_id) as (archive,pages):
            return archive.read(pages[number%3])
    with ThreadPoolExecutor(max_workers=8) as workers:
        assert list(workers.map(read,range(32)))==[picture()]*32
    assert path.read_bytes()==before
    path.rename(path.with_suffix('.moved'))


def test_folder_manifest_follows_index_listing_with_frozen_times(library,monkeypatch):
    source,connect,media,db=library
    chapter='Story/Chapter 2';folder=media/chapter;stamp=folder.stat()
    expected=['1.png','2.png','10.png']
    natural=engine.natural;sorted_names=[]
    def counted(name):
        sorted_names.append(name)
        return natural(name)
    monkeypatch.setattr(engine,'natural',counted)
    assert [Path(name).name for name in engine.folder_pages(db,source.source_id,chapter)]==expected
    assert len(sorted_names)==3
    assert [Path(name).name for name in engine.folder_pages(db,source.source_id,chapter)]==expected
    assert len(sorted_names)==3
    monkeypatch.setattr(index,'_now',lambda:'frozen')
    (folder/'3.png').write_bytes(picture())
    os.utime(folder,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    with index.open_index(db) as connection:index.scan_source(connection,source.source_id,media)
    assert [Path(name).name for name in engine.folder_pages(db,source.source_id,chapter)]==['1.png','2.png','3.png','10.png']
    (folder/'1.png').rename(folder/'first.png')
    os.utime(folder,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    with index.open_index(db) as connection:index.scan_source(connection,source.source_id,media)
    assert [Path(name).name for name in engine.folder_pages(db,source.source_id,chapter)]==['2.png','3.png','10.png','first.png']


def test_manifest_entry_page_and_name_budgets():
    entries=ManifestCache(max_entries=2)
    for name in ['first','second','third']:entries.put(name,1,[name])
    assert entries.get('first',1) is None
    assert entries.get('second',1)==('second',)
    pages=ManifestCache(max_pages=3)
    pages.put('first',1,['1','2']);pages.put('second',1,['3','4'])
    assert pages.get('first',1) is None
    assert pages.get('second',1)==('3','4')
    names=ManifestCache(max_name_bytes=6)
    names.put('first',1,['1234']);names.put('second',1,['5678'])
    assert names.get('first',1) is None
    names.put('oversized',1,['1234567'])
    assert names.get('oversized',1) is None
    assert names.get('second',2) is None


def test_windows_identity_tolerates_creation_time_reporting_difference(monkeypatch):
    handle = SimpleNamespace(st_dev=1, st_ino=2, st_size=3, st_mtime_ns=4, st_ctime_ns=5)
    named = SimpleNamespace(**vars(handle))
    named.st_ctime_ns = 6
    monkeypatch.setattr(page_cache, 'os', SimpleNamespace(name='nt'))
    assert page_cache.file_identity(handle) == page_cache.file_identity(named)
    for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns'):
        replaced = SimpleNamespace(**vars(handle))
        setattr(replaced, field, 99)
        assert page_cache.file_identity(handle) != page_cache.file_identity(replaced)
    monkeypatch.setattr(page_cache, 'os', SimpleNamespace(name='posix'))
    assert page_cache.file_identity(handle) != page_cache.file_identity(named)


@pytest.mark.parametrize('kind,chapter', [('folder','Story/Chapter 2'), ('archive','Story/Chapter 10.cbz')])
def test_original_bytes_revisions_and_conditional_response(library,kind,chapter):
    source,connect,media,db=library;manga.adopt(source.source_id)
    assert router.pages(source.source_id,chapter,kind)=={'count':3}
    metadata=router.pages(source.source_id,chapter,kind,True)
    assert metadata['count']==len(metadata['revisions'])==3
    assert len(metadata['revision'])==64
    revision=metadata['revisions'][0]
    response=router.page(source.source_id,chapter,kind,0,False,'original',revision)
    assert response.body==picture()
    assert response.media_type=='image/png'
    assert response.headers['cache-control']=='private, no-cache'
    assert response.headers['x-content-type-options']=='nosniff'
    assert response.headers['x-manga-revision']==revision
    etag=response.headers['etag']
    same=router.page(source.source_id,chapter,kind,0,False,'original',revision,'W/'+etag+', "other"')
    assert same.status_code==304 and same.body==b''
    with pytest.raises(HTTPException) as stale:
        router.page(source.source_id,chapter,kind,0,False,'original','0'*64,etag)
    assert stale.value.status_code==409
    with connect() as connection:sources.update_source(connection,source.source_id,visible=False)
    with pytest.raises(HTTPException) as hidden:
        router.page(source.source_id,chapter,kind,0,False,'original',revision,etag)
    assert hidden.value.status_code==404


def test_representation_and_revision_query_validation(library):
    source,connect,media,db=library;manga.adopt(source.source_id)
    app=FastAPI();app.include_router(router.router)
    async def request(query,path='/api/manga/page'):
        messages=[]
        async def receive():return {'type':'http.request','body':b'','more_body':False}
        async def send(message):messages.append(message)
        await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'GET',
                   'scheme':'http','path':path,'raw_path':path.encode(),
                   'root_path':'','query_string':urlencode(query).encode(),'headers':[],
                   'client':('127.0.0.1',1),'server':('127.0.0.1',80)},receive,send)
        start=next(message for message in messages if message['type']=='http.response.start')
        body=b''.join(message.get('body',b'') for message in messages if message['type']=='http.response.body')
        return start['status'],dict(start['headers']),body
    query={'source_id':source.source_id,'path':'Story/Chapter 2'}
    for field,value in [('revision','old'),('revision','g'*64),('representation','html')]:
        assert asyncio.run(request({**query,field:value}))[0]==422
    status,headers,body=asyncio.run(request({**query,'representation':'original'}))
    assert status==200 and body==picture() and headers[b'content-type']==b'image/png'
    assert asyncio.run(request(query))[1][b'content-type']==b'image/webp'
    status,headers,body=asyncio.run(request({**query,'metadata':'true'},'/api/manga/pages'))
    assert status==200 and headers[b'cache-control']==b'no-store'
    assert asyncio.run(request({},'/api/manga/library'))[1][b'cache-control']==b'no-store'


def test_changed_same_size_and_timestamp_original_does_not_reuse_bytes(library,monkeypatch):
    source,connect,media,db=library;manga.adopt(source.source_id)
    path=media/'Story/Chapter 2/1.png'
    data=BytesIO();Image.new('RGB',(60,90),'red').save(data,'BMP')
    path.write_bytes(data.getvalue())
    before=router.page(source.source_id,'Story/Chapter 2','folder',0,False)
    stamp=path.stat();replacement=BytesIO();Image.new('RGB',(60,90),'blue').save(replacement,'BMP')
    assert len(replacement.getvalue())==len(path.read_bytes())
    path.write_bytes(replacement.getvalue());os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    after=router.page(source.source_id,'Story/Chapter 2','folder',0,False,if_none_match=before.headers['etag'])
    assert after.status_code==200 and after.body!=before.body
    assert after.headers['etag']!=before.headers['etag']
    metadata=router.pages(source.source_id,'Story/Chapter 2','folder',True)
    path.write_bytes(b'<html>not an image</html>')
    with pytest.raises(HTTPException):
        router.page(source.source_id,'Story/Chapter 2','folder',0,False,'original',metadata['revisions'][0])


def test_original_sniffs_mime_preserves_exif_and_refuses_corrupt_or_oversized(library,monkeypatch):
    source,connect,media,db=library;manga.adopt(source.source_id)
    path=media/'Story/Chapter 2/1.png'
    data=BytesIO();image=Image.new('RGB',(120,60),'green');exif=Image.Exif();exif[274]=6
    image.save(data,'JPEG',exif=exif);path.write_bytes(data.getvalue())
    response=router.page(source.source_id,'Story/Chapter 2','folder',0,False,'original')
    assert response.media_type=='image/jpeg' and response.body==data.getvalue()
    monkeypatch.setattr(engine,'MAX_PIXELS',100)
    with pytest.raises(HTTPException):router.page(source.source_id,'Story/Chapter 2','folder',0,False,'original')
    monkeypatch.setattr(engine,'MAX_PIXELS',24_000_000)
    path.write_bytes(picture()[:30])
    with pytest.raises(HTTPException):router.page(source.source_id,'Story/Chapter 2','folder',0,False,'original')


@pytest.mark.parametrize('format', ['BMP','GIF'])
def test_unsupported_and_animated_pages_require_explicit_conversion(library,format):
    source,connect,media,db=library;manga.adopt(source.source_id)
    data=BytesIO();image=Image.new('RGB',(60,90),'red')
    if format=='GIF':image.save(data,format,save_all=True,append_images=[Image.new('RGB',(60,90),'blue')],duration=100,loop=0)
    else:image.save(data,format)
    path=media/'Story/Chapter 2/1.png';path.write_bytes(data.getvalue())
    with pytest.raises(HTTPException) as unsupported:
        router.page(source.source_id,'Story/Chapter 2','folder',0,False,'original')
    assert unsupported.value.status_code==415
    converted=router.page(source.source_id,'Story/Chapter 2','folder',0,False,'webp')
    assert converted.media_type=='image/webp' and Image.open(BytesIO(converted.body)).size==(60,90)
    assert path.read_bytes()==data.getvalue()


def test_parallel_original_validation_and_webp_encoding_coalesce(library,monkeypatch):
    source,connect,media,db=library;manga.adopt(source.source_id)
    validate=engine.original_page;render=engine.render_page;calls={'original':0,'webp':0}
    def counted_original(raw):calls['original']+=1;time.sleep(.02);return validate(raw)
    def counted_webp(raw,cover=False):calls['webp']+=1;time.sleep(.02);return render(raw,cover)
    monkeypatch.setattr(engine,'original_page',counted_original)
    monkeypatch.setattr(engine,'render_page',counted_webp)
    for representation in ['original','webp']:
        with ThreadPoolExecutor(max_workers=8) as workers:
            results=list(workers.map(lambda _:router.page(source.source_id,'Story/Chapter 10.cbz','archive',0,False,representation).body,range(16)))
        assert len(set(results))==1
    assert calls=={'original':1,'webp':1}


def test_cover_cache_persists_after_fresh_process_and_obeys_shared_disk_limit(library,monkeypatch):
    source,connect,media,db=library;manga.adopt(source.source_id)
    cover=router.page(source.source_id,'Story/Chapter 10.cbz','archive',0,True)
    paths=list(thumbnails.cache_entries());assert len(paths)==1
    assert thumbnails.thumbnail_cache_status()['bytes']==len(cover.body)
    # A new interpreter has no manifest/response cache. Inject only scratch
    # thumbnail configuration so no personal config/database is even loaded.
    program='''import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
sys.modules['config']=SimpleNamespace(THUMB_DIR=Path(sys.argv[2]),get_thumbnail_cache_limit_bytes=lambda:67108864)
from modules.manga import library as engine
def unexpected(*args,**kwargs):raise AssertionError('Cover encoded again after restart')
engine.render_page=unexpected
source=SimpleNamespace(source_id=sys.argv[4],path=sys.argv[3])
result,_=engine.page_response(source,'Story/Chapter 10.cbz','archive',0,None,[],True)
print(len(result.content))
'''
    process=subprocess.run([sys.executable,'-c',program,str(Path(__file__).resolve().parents[1]/'backend'),str(thumbnails.THUMB_DIR),str(media),source.source_id],capture_output=True,text=True,check=True)
    assert int(process.stdout.strip())==len(cover.body)
    path=media/'Story/Chapter 2/1.png';path.write_bytes(picture('blue'))
    monkeypatch.setattr(thumbnails,'get_thumbnail_cache_limit_bytes',lambda:1)
    assert router.page(source.source_id,'Story/Chapter 2','folder',0,True).body
    assert thumbnails.thumbnail_cache_status()['bytes']<=1
    assert path.read_bytes()==picture('blue')


def test_response_cache_entry_and_byte_budgets_and_separate_covers(library):
    cache=ResponseCache(max_entries=2,max_bytes=6)
    make=lambda:PageData(b'1234','image/png')
    cache.get_or_create('first',make);cache.get_or_create('second',make)
    assert len(cache._items)==1 and cache._bytes==4
    cache.get_or_create('oversized',lambda:PageData(b'1234567','image/png'))
    assert len(cache._items)==1 and cache._bytes==4
    cache=ResponseCache(max_entries=1,max_bytes=100)
    cache.get_or_create('first',make);cache.get_or_create('second',make)
    assert list(cache._items)==['second']
    source,connect,media,db=library;manga.adopt(source.source_id)
    router.page(source.source_id,'Story/Chapter 2','folder',0,False,'original')
    kept=list(engine.responses._items)
    router.page(source.source_id,'Story/Chapter 2','folder',0,True)
    thumbnails.clear_thumbnail_cache()
    assert list(engine.responses._items)==kept


def test_old_page_revision_rejected_after_rescan_or_archive_replacement(library):
    source,connect,media,db=library;manga.adopt(source.source_id)
    chapter='Story/Chapter 2';before=router.pages(source.source_id,chapter,'folder',True)
    folder=media/chapter;(folder/'0.png').write_bytes(picture('red'))
    with index.open_index(db) as connection:index.scan_source(connection,source.source_id,media)
    after=router.pages(source.source_id,chapter,'folder',True)
    assert before['revision']!=after['revision'] and after['count']==4
    with pytest.raises(HTTPException) as changed:router.page(source.source_id,chapter,'folder',0,False,'original',before['revisions'][0])
    assert changed.value.status_code==409
    chapter='Story/Chapter 10.cbz';before=router.pages(source.source_id,chapter,'archive',True)
    with zipfile.ZipFile(media/chapter,'w') as archive:archive.writestr('different.png',picture('blue'))
    with pytest.raises(HTTPException) as changed:router.page(source.source_id,chapter,'archive',0,False,'original',before['revisions'][0])
    assert changed.value.status_code==409
