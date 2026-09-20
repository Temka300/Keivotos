"""The FastAPI application object and its HTTP middleware.

Moved verbatim from ``core.py``, which no longer constructs the application.
``server.py`` imports ``app`` from here and attaches the routers; ``core`` keeps
re-exporting it while unconverted routers still wildcard-import the facade.

The browser-access middleware is a security control: it rejects any request
whose Host, Origin, or Fetch Metadata does not match the active local origin.
No ``core`` import.
"""
from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException

from lifecycle import lifespan
from product import DISPLAY_NAME, VERSION
from security import validate_local_browser_request


app = FastAPI(title=DISPLAY_NAME, version=VERSION, lifespan=lifespan)


@app.middleware("http")
async def restrict_local_browser_access(request: Request, call_next):
    rejection = validate_local_browser_request(
        host_header=request.headers.get("host", ""),
        scheme=request.url.scheme,
        origin_header=request.headers.get("origin"),
        fetch_site_header=request.headers.get("sec-fetch-site"),
        lan_host=os.environ.get("KEIVOTOS_LAN_HOST"),
    )
    if rejection is not None:
        status_code, detail = rejection
        return JSONResponse(status_code=status_code, content={"detail": detail})
    return await call_next(request)


@app.middleware("http")
async def add_server_timing_header(request: Request, call_next):
    started_at = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started_at) * 1000
    response.headers["Server-Timing"] = f'app;dur={duration_ms:.2f};desc="{DISPLAY_NAME}"'
    return response


@app.exception_handler(HTTPException)
async def log_http_error(request: Request, exception):
    logging.getLogger("keivotos.requests").warning(
        "%s %s: HTTP %s: %s", request.method, request.url.path,
        exception.status_code, exception.detail)
    return await http_exception_handler(request, exception)
