"""Experimental YouTube acquisition; originals belong to registered Files folders."""
from pathlib import Path
from module_descriptor import ModuleDescriptor

SCHEMA = '''
CREATE TABLE IF NOT EXISTS youtube_preferences (
 id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL DEFAULT 'default', custom_source TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS youtube_downloads (
 id TEXT PRIMARY KEY, url TEXT NOT NULL, source_id TEXT NOT NULL,
 root TEXT NOT NULL, video TEXT NOT NULL, audio TEXT NOT NULL,
 title TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'queued',
 progress REAL NOT NULL DEFAULT 0, path TEXT NOT NULL DEFAULT '',
 thumbnail TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
'''


def _routers():
    from modules.youtube.router import router
    return [router]


def _tasks():
    from modules.youtube.jobs import run_queue
    return [('youtube-downloads', run_queue())]


def _publish(connection):
    connection.executescript(SCHEMA)
    connection.commit()


def _startup():
    from modules.youtube.jobs import recover
    recover()


def adopt(source_id: str) -> dict:
    from database import get_user_db
    from files_base import sources
    with get_user_db() as connection:
        if sources.get_source(connection, source_id) is None:
            raise ValueError("Unknown folder")
        sources.update_source(connection, source_id, role="youtube")
    return {"source_id": source_id, "role": "youtube"}


def release(source_id: str, forget: bool = False) -> dict:
    from database import get_user_db
    from files_base import sources
    with get_user_db() as connection:
        source = sources.get_source(connection, source_id)
        if source is None or source.role != "youtube":
            raise ValueError("Unknown YouTube folder")
        if forget:
            sources.remove_source(connection, source_id)
        else:
            sources.update_source(connection, source_id, role="files")
    return {"source_id": source_id, "role": "files", "forgotten": forget}


def descriptor(suite_home: Path, version: str):
    return ModuleDescriptor(
        slug='youtube', name='YouTube', description='Download videos to your local folders.',
        experimental=True, home=suite_home/'modules/youtube', database=suite_home/'base/files.sqlite',
        credentials=None, api_prefix='/api/youtube', log_prefix='youtube',
        user_agent=f'Keivotos/{version} (YouTube)', disableable=True, is_base=False,
        user_schema_provider=lambda: SCHEMA, publish_hook=_publish, router_provider=_routers,
        adopt_hook=adopt, release_hook=release, startup_hook=_startup, background_tasks_hook=_tasks)
