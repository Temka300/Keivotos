"""Manga endpoints: indexed ownership plus shared containment policy on every read."""
import logging
from threading import BoundedSemaphore
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
import config
from database import get_user_db
from files_base import sources, serving
from modules.manga import library as engine

router = APIRouter()
logger = logging.getLogger('keivotos.manga')
_render_slots = BoundedSemaphore(2)


def owners():
    with get_user_db() as connection:
        return [s for s in sources.list_sources(connection) if s.role == 'manga' and s.visible]


def find_chapter(source_id, path, kind):
    source = next((s for s in owners() if s.source_id == source_id), None)
    if source and engine.chapter_exists(config.FILES_DB_PATH, source_id, path, kind):
        return source
    raise HTTPException(404, 'Chapter is unavailable')


def failed(source_id, path, exc):
    logger.warning('Manga read failed: source=%r chapter=%r error=%s: %s', source_id, path, type(exc).__name__, exc)
    if isinstance(exc, serving.ServeDenied):
        raise HTTPException(exc.status_code, 'Chapter is unavailable. See Logs.') from exc
    raise HTTPException(422, 'This chapter cannot be opened. See Logs.') from exc


@router.get('/api/manga/library')
def library(q: str = Query('', max_length=256), offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=120)):
    items = [s for s in engine.catalog(config.FILES_DB_PATH, owners()) if q.strip().casefold() in s['name'].casefold()]
    return {'items': [{'source_id': s['source_id'], 'path': s['path'], 'name': s['name'], 'cover': s['chapters'][0]}
                      for s in items[offset:offset+limit]], 'total': len(items)}


@router.get('/api/manga/chapters')
def chapters(source_id: str = Query(..., max_length=256), path: str = Query('', max_length=4096)):
    for series in engine.catalog(config.FILES_DB_PATH, owners()):
        if series['source_id'] == source_id and series['path'] == path:
            return {'items': series['chapters']}
    raise HTTPException(404, 'Manga is unavailable')


@router.get('/api/manga/pages')
def pages(source_id: str = Query(..., max_length=256), path: str = Query('', max_length=4096), kind: Literal['folder','archive'] = 'folder'):
    source = find_chapter(source_id, path, kind)
    try:
        target = serving.resolve_within_source(source.path, path, [config.SUITE_HOME])
        if kind == 'archive':
            with engine.open_archive(target) as (_, entries):
                count = len(entries)
        else:
            count = len(engine.folder_pages(config.FILES_DB_PATH, source_id, path))
        if not count:
            raise ValueError('No readable image pages')
        return {'count': count}
    except Exception as exc:
        failed(source_id, path, exc)


@router.get('/api/manga/page')
def page(source_id: str = Query(..., max_length=256), path: str = Query('', max_length=4096),
         kind: Literal['folder','archive'] = 'folder', page: int = Query(0, ge=0), cover: bool = False):
    source = find_chapter(source_id, path, kind)
    # Bound simultaneous image decodes; no extraction, persistent cache or DB write.
    with _render_slots:
        try:
            content = engine.read_page(source, path, kind, page, config.FILES_DB_PATH, [config.SUITE_HOME], cover)
            return Response(content, media_type='image/webp', headers={'X-Content-Type-Options':'nosniff', 'Cache-Control':'no-store'})
        except Exception as exc:
            failed(source_id, path, exc)
