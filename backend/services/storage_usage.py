"""Read-only app-data inventory; media roots are never traversed."""
from pathlib import Path
import os
import config
from thumbnails import cache_entries, thumbnail_cache_status


def usage():
    modules=list(config.MODULE_REGISTRY)
    homes=sorted([(Path(m.home).absolute(),m.slug) for m in modules],key=lambda pair:len(pair[0].parts),reverse=True)
    roots={Path(config.SUITE_HOME).absolute(),*(home for home,_ in homes)}
    databases={Path(config.USER_DB_PATH).absolute(),*(Path(m.database).absolute() for m in modules)}
    roots.update(path.parent for path in databases if path.parent in {home for home,_ in homes})
    backups=Path(config.get_backup_config()['destination']).expanduser().absolute()
    logs=Path(config.LOG_DIR).absolute()
    thumbs={p.absolute() for p in cache_entries()}
    counts={'thumbnails':0,'cache':0,'backups':0,'databases':0,'logs':0,**{m.slug:0 for m in modules}}
    seen=set();total=0;unreadable=0
    def add(path):
        nonlocal total,unreadable
        try:
            if path.is_symlink() or not path.is_file():return
            stat=path.stat();identity=(stat.st_dev,stat.st_ino) if stat.st_ino else str(path)
            if identity in seen:return
            seen.add(identity);total+=stat.st_size
            if path in thumbs:key='thumbnails'
            elif path==backups or backups in path.parents:key='backups'
            elif any(path==db or str(path) in (str(db)+'-wal',str(db)+'-shm',str(db)+'-journal') for db in databases) or path.suffix.lower() in ('.sqlite','.sqlite3','.db'):key='databases'
            elif logs in path.parents:key='logs'
            else:key=next((slug for home,slug in homes if home in path.parents),None)
            if key:counts[key]+=stat.st_size
        except OSError:unreadable+=1
    def linked(path):
        return path.is_symlink() or os.path.normcase(str(path.resolve()))!=os.path.normcase(str(path.absolute()))
    for root in sorted(roots,key=lambda p:len(p.parts)):
        if linked(root) or not root.is_dir():continue
        def failed(_error):
            nonlocal unreadable
            unreadable+=1
        for directory,dirs,files in os.walk(root,followlinks=False,onerror=failed):
            dirs[:]=[d for d in dirs if not linked(Path(directory,d))]
            for name in files:add(Path(directory,name))
    # Only backup bundles are app data in an external custom backup destination.
    if backups.is_dir() and not linked(backups):
        from backup_bundle import SUPPORTED_BACKUP_SUFFIXES
        try:
            for path in backups.iterdir():
                if path.suffix.lower() in SUPPORTED_BACKUP_SUFFIXES:add(path)
        except OSError:unreadable+=1
    return {'data_location':str(config.SUITE_HOME.resolve()),'total_bytes':total,
            'categories':counts,'modules':[{'id':m.slug,'name':m.name} for m in modules],
            'thumbnails':thumbnail_cache_status(),'cleanup_on_startup':config.get_thumbnail_cleanup_on_startup(),
            'unreadable':unreadable}
