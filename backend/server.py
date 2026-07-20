"""FastAPI composition root for Danbooru."""

from config import CODE_ROOT
from fastapi.responses import FileResponse
from core import app
from routers import artists, collections, discovery, folders, images_media, stats, tags, tools, user_library

for domain_router in (
    images_media.router, discovery.router, tags.router, artists.router,
    folders.router, user_library.router, collections.router, stats.router, tools.router,
):
    app.include_router(domain_router)

FRONTEND_DIST = CODE_ROOT / 'frontend' / 'dist'

if FRONTEND_DIST.exists():
    from fastapi.staticfiles import StaticFiles

    @app.get('/')
    async def serve_index():
        # index.html points at content-hashed assets. It must be revalidated on
        # every navigation so an open installation cannot keep booting an older
        # bundle after an update. The hashed JS/CSS files remain cacheable via
        # StaticFiles.
        return FileResponse(
            FRONTEND_DIST / 'index.html',
            headers={
                'Cache-Control': 'no-store, no-cache, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
            },
        )

    app.mount('/', StaticFiles(directory=str(FRONTEND_DIST), html=True), name='frontend')

if __name__ == '__main__':
    import uvicorn
    from product import DEFAULT_HOST, DEFAULT_PORT

    uvicorn.run('server:app', host=DEFAULT_HOST, port=DEFAULT_PORT, reload=True)
