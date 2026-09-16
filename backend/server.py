"""FastAPI composition root for Keivotos."""

from config import CODE_ROOT, MODULE_REGISTRY
from fastapi.responses import FileResponse
from app_factory import app
from routers import suite, user_settings

# Suite-shell routers: the module registry itself and suite-level user settings.
# They belong to no module and are always mounted.
for shell_router in (suite.router, user_settings.router):
    app.include_router(shell_router)

# Every registered surface contributes its own routers — the Files base and each
# optional module. Adding a module is a descriptor field, never an edit here.
# Routers stay always-mounted (contract §8); endpoints gate on enabled state.
for descriptor in MODULE_REGISTRY:
    for module_router in descriptor.routers():
        app.include_router(module_router)

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
