"""Read-only accounting and strictly disposable thumbnail cleanup."""
from pathlib import Path
from types import SimpleNamespace
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import config
import thumbnails
from services import storage_usage
from routers import cache, storage


def write(path,size):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x'*size);return path


def test_cleanup_preserves_current_shared_thumbnails_and_all_durable_files(tmp_path,monkeypatch):
    root=tmp_path/'thumbnails';monkeypatch.setattr(thumbnails,'THUMB_DIR',root)
    current=write(root/('a'*32+'_v4.webp'),30)
    old=write(root/('a'*32+'_v3.webp'),20)
    durable=[write(root/name,7) for name in ['user.sqlite','settings.json','original.webp','attachments/original.webp']]
    outside=write(tmp_path/'outside.webp',9)
    (root/('b'*32+'_v4.webp')).symlink_to(outside)
    assert cache._valid_thumbnail_keys() is None
    assert thumbnails.cleanup_thumbnail_cache(None)['removed']==1
    assert current.exists() and not old.exists()
    assert thumbnails.thumbnail_cache_status()['tier_bytes']['300']==30
    assert thumbnails.clear_thumbnail_cache()==1
    assert all(p.exists() for p in durable) and outside.read_bytes()==b'x'*9
    assert root.exists()


def test_linked_cache_root_and_nested_links_are_never_cleared(tmp_path,monkeypatch):
    outside=tmp_path/'outside';file=write(outside/('a'*32+'_v4.webp'),12)
    linked=tmp_path/'linked';linked.symlink_to(outside,target_is_directory=True)
    monkeypatch.setattr(thumbnails,'THUMB_DIR',linked)
    assert thumbnails.clear_thumbnail_cache()==0
    assert thumbnails.cleanup_thumbnail_cache(None)['removed']==0
    assert thumbnails.prune_thumbnail_cache(0)['removed']==0
    assert file.exists()


def test_inventory_is_disjoint_and_excludes_original_roots(tmp_path,monkeypatch):
    home=tmp_path/'data';base=home/'base';video=home/'modules/video'
    db=write(base/'files.sqlite',50);write(home/'user.sqlite',100)
    write(base/'attachments/file.png',20);write(video/'owned.json',9)
    write(home/'logs/runtime.log',11)
    thumbs=base/'thumbnails';write(thumbs/('a'*32+'_v4_600.webp'),30)
    from backup_bundle import BACKUP_SUFFIX
    backup=tmp_path/'backup';write(backup/('saved'+BACKUP_SUFFIX),40)
    original=write(tmp_path/'media/movie.mp4',1000)
    (base/'linked-media').symlink_to(original.parent,target_is_directory=True)
    modules=[SimpleNamespace(slug='files',name='Files',home=base,database=db),SimpleNamespace(slug='video',name='Video',home=video,database=db)]
    monkeypatch.setattr(config,'MODULE_REGISTRY',modules)
    monkeypatch.setattr(config,'SUITE_HOME',home);monkeypatch.setattr(config,'USER_DB_PATH',home/'user.sqlite');monkeypatch.setattr(config,'LOG_DIR',home/'logs')
    monkeypatch.setattr(config,'get_backup_config',lambda:{'destination':str(backup)})
    monkeypatch.setattr(thumbnails,'THUMB_DIR',thumbs)
    result=storage_usage.usage()
    assert result['total_bytes']==260
    assert result['categories']=={'thumbnails':30,'cache':0,'backups':40,'databases':150,'logs':11,'files':20,'video':9}
    assert result['thumbnails']['tier_bytes']['600']==30
    assert original.stat().st_size==1000


def test_startup_preference_is_strict_and_persisted(monkeypatch):
    values={};monkeypatch.setattr(config,'_cfg',values)
    monkeypatch.setattr(config,'save_config',lambda update:values.update(update))
    assert not config.get_thumbnail_cleanup_on_startup()
    assert storage.cache_preferences(storage.CachePreferences(cleanup_on_startup=True))=={'cleanup_on_startup':True}
    assert config.get_thumbnail_cleanup_on_startup()
