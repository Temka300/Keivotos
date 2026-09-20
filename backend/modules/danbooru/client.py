"""Credentialed Danbooru JSON requests — the module's HTTP boundary.

Extracted verbatim from ``core.py``. This is the one place that talks to
danbooru.donmai.us: it applies the module's user agent, attaches saved
credentials when present, and turns transport failures into the HTTP errors the
routers already return. It writes no SQLite, reads no UI state, and does not
import ``core``.

Lives under ``modules/danbooru/`` rather than a shared ``services/`` directory
because it is Danbooru-specific: moving it here is part of getting the module's
implementation behind its own boundary (SUITE_MODULE_CONTRACT.md section 13).
"""
from __future__ import annotations

import base64
import logging
import http.client
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import HTTPException

from config import DANBOORU_MODULE
from modules.danbooru.credentials import effective_credentials
from modules.danbooru.network import read_json
from product import DISPLAY_NAME, VERSION


DANBOORU_BASE_URL = "https://danbooru.donmai.us"
DANBOORU_POST_URL_PREFIX = f"{DANBOORU_BASE_URL}/posts/"

# The scraper identifies as the module, falling back to the suite when the
# Danbooru descriptor is absent from the registry.
USER_AGENT = (
    DANBOORU_MODULE.user_agent
    if DANBOORU_MODULE is not None
    else f"{DISPLAY_NAME}/{VERSION}"
)


def danbooru_json(endpoint: str, params: dict[str, str | int], timeout: float = 20.0) -> Any:
    query = urllib.parse.urlencode(params)
    url = f"{DANBOORU_BASE_URL}{endpoint}"
    if query:
        url = f"{url}?{query}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    username, api_key, _source = effective_credentials()
    if username and api_key:
        token = base64.b64encode(f"{username}:{api_key}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(url, headers=headers)
    def emit(message: str) -> None:
        level = logging.ERROR if message.startswith("ERROR:") else logging.WARNING if message.startswith("WARNING:") else logging.INFO
        logging.getLogger("keivotos.danbooru.requests").log(level, "%s", message)
    try:
        return read_json(request, timeout=timeout, retries=2, emit=emit, secrets=(api_key or "",))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(404, "Danbooru metadata not found") from exc
        raise HTTPException(502, f"Failed to fetch Danbooru metadata: {exc}") from exc
    except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
        raise HTTPException(502, f"Failed to fetch Danbooru metadata: {exc}") from exc


def normalize_danbooru_post_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("post"), dict):
        return data["post"]
    return data if isinstance(data, dict) else {}
