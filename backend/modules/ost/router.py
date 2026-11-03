"""OST role admission and guarded local discovery; media uses Files routes."""
from fastapi import APIRouter, HTTPException, Query

import config
from database import get_user_db
from files_base import serving, sources
from modules.ost import library as discovery

router = APIRouter()


def registered_sources():
    with get_user_db() as connection:
        sources.ensure_sources_schema(connection)
        return sources.list_sources(connection)


@router.get('/api/ost/folders')
def folders():
    registered = registered_sources()
    return [{'source_id': source.source_id, 'name': source.display_name,
             'available': discovery.available(source, '', True,
                 discovery.forbidden_roots(source, registered, config.SUITE_HOME))}
            for source in registered if source.role == 'ost' and source.visible]


@router.get('/api/ost/library')
def library(source_id: str = Query(..., max_length=256),
            parent: str = Query('', max_length=4096),
            offset: int = Query(0, ge=0), limit: int = Query(120, ge=1, le=240)):
    registered = registered_sources()
    source = next((source for source in registered
                   if source.source_id == source_id and source.role == 'ost' and source.visible), None)
    if source is None:
        raise HTTPException(404, 'OST folder is unavailable')
    try:
        return discovery.directory(config.FILES_DB_PATH, source, registered,
                                   config.SUITE_HOME, parent, offset, limit)
    except serving.ServeDenied as error:
        raise HTTPException(error.status_code, error.detail) from error
    except (OSError, ValueError) as error:
        raise HTTPException(404, 'OST folder is unavailable') from error
