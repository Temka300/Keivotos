"""Bounded, observable retries for idempotent Danbooru JSON reads."""
from __future__ import annotations

import http.client
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Any

from runtime_logging import redact_log_text


def failure_kind(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        if error.code in (401, 403):
            return "authentication"
        if error.code == 429:
            return "rate limit"
        return "server" if error.code in (500, 502, 503, 504) else "request"
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "certificate"
    if isinstance(reason, (TimeoutError, ConnectionError, http.client.HTTPException)):
        return "connection"
    if isinstance(error, urllib.error.URLError):
        return "connection"
    return "invalid response" if isinstance(error, (ValueError, UnicodeError)) else "local"


def retry_delay(error: Exception, attempt: int) -> float | None:
    kind = failure_kind(error)
    if kind not in {"connection", "rate limit", "server"}:
        return None
    delay = min(2 ** (attempt + 1), 30)
    if kind == "rate limit":
        delay = min(60 * (attempt + 1), 300)
    if isinstance(error, urllib.error.HTTPError) and error.headers:
        value = error.headers.get("Retry-After")
        if value:
            try:
                seconds = float(value)
            except ValueError:
                try:
                    target = parsedate_to_datetime(value)
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=timezone.utc)
                    seconds = (target - datetime.now(timezone.utc)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    seconds = 0
            # Never retry earlier than requested. Long waits require a later run.
            if seconds > 300:
                return None
            if seconds > 0:
                delay = max(delay, seconds)
    return delay


def read_json(request: urllib.request.Request, *, timeout: float, retries: int,
              emit: Callable[[str], None], secrets: tuple[str, ...] = (),
              not_found_empty: bool = False) -> Any:
    retries = max(0, min(retries, 5))
    endpoint = urllib.parse.urlsplit(request.full_url).path
    for attempt in range(retries + 1):
        context = f"GET {endpoint} (attempt {attempt + 1}/{retries + 1})"
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
                emit(f"Request: {context} succeeded")
                return result
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as error:
            if isinstance(error, urllib.error.HTTPError) and error.code == 404 and not_found_empty:
                emit(f"Request: {context}: HTTP 404, no matching post")
                return []
            kind = failure_kind(error)
            description = f"HTTP {error.code}: {error.reason}" if isinstance(error, urllib.error.HTTPError) else str(error)
            detail = redact_log_text(description, secrets)
            delay = retry_delay(error, attempt)
            if attempt < retries and delay is not None:
                emit(f"WARNING: {context}: {kind}: {detail}; retry in {delay:g}s")
                time.sleep(delay)
                continue
            ending = "retries exhausted" if delay is not None else "request stopped"
            emit(f"ERROR: {context}: {kind}: {detail}; {ending}")
            raise
