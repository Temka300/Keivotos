"""Real isolated image/ZIP fixtures: order, preservation and rejected reads."""
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import sqlite3
import stat
import sys
import zipfile

import pytest
from PIL import Image
from fastapi import HTTPException
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import database
from files_base import sources, index
from modules import manga
from modules.manga import library as engine, router


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
    with connect() as c:sources.update_source(c,source.source_id,visible=False)
    with pytest.raises(HTTPException):router.page(source.source_id,'Story/Chapter 2','folder',0,False)


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
