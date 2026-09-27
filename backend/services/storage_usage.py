"""Read-only app-data inventory; media roots are never traversed."""
from pathlib import Path
import os
import sqlite3
import config
from files_base import index, sources
from thumbnails import cache_entries, thumbnail_cache_status


def _readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def library_files_usage() -> dict:
    """Summarize the last Files index without walking or opening media roots."""
    empty = {"categories": [], "total_bytes": 0, "total_files": 0,
             "unknown_files": 0, "index_unavailable": False}
    user_path = Path(config.USER_DB_PATH)
    if not user_path.is_file():
        return empty
    try:
        with _readonly(user_path) as user_connection:
            source_list = sources.list_sources(user_connection)
    except (OSError, sqlite3.Error):
        return {**empty, "index_unavailable": True}
    if not source_list:
        return empty
    file_path = Path(config.FILES_DB_PATH)
    if not file_path.is_file():
        return {**empty, "index_unavailable": True}
    grouped: dict[str, dict] = {}
    owner_names = {descriptor.slug: descriptor.name for descriptor in config.MODULE_REGISTRY}
    try:
        with _readonly(file_path) as connection:
            for source in source_list:
                descendants = sources.descendant_sources(source, source_list)
                relative_roots = [Path(os.path.relpath(child.path, source.path)).as_posix()
                                  for child in descendants]
                bytes_used, file_count, unknown = index.source_size_totals(
                    connection, source.source_id, relative_roots)
                role = source.role if source.role in owner_names else "other"
                entry = grouped.setdefault(role, {"id": role, "name": "Other", "bytes": 0,
                                                  "files": 0, "unknown_files": 0})
                entry["bytes"] += bytes_used
                entry["files"] += file_count
                entry["unknown_files"] += unknown
    except (OSError, sqlite3.Error):
        return {**empty, "index_unavailable": True}
    ordered = []
    for slug, name in owner_names.items():
        if slug in grouped:
            entry = grouped.pop(slug)
            entry["name"] = name
            ordered.append(entry)
    if "other" in grouped:
        ordered.append(grouped["other"])
    return {"categories": ordered,
            "total_bytes": sum(entry["bytes"] for entry in ordered),
            "total_files": sum(entry["files"] for entry in ordered),
            "unknown_files": sum(entry["unknown_files"] for entry in ordered),
            "index_unavailable": False}


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
            'unreadable':unreadable,'library_files':library_files_usage()}
