"""Local Danbooru credentials with Windows DPAPI protection."""
from __future__ import annotations

import base64
import ctypes
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from config import CREDENTIALS_PATH


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _protect(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("Saving API keys currently requires Windows DPAPI; use environment variables on this platform")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, source_buffer = _blob(value.encode("utf-8"))
    output = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(source), "Danbooru API key", None, None, None, 0,
        ctypes.byref(output),
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(output.pbData, output.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        _ = source_buffer
        kernel32.LocalFree(output.pbData)


def _unprotect(value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("Saved API key can only be decrypted by Windows DPAPI")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source, source_buffer = _blob(base64.b64decode(value))
    output = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        _ = source_buffer
        kernel32.LocalFree(output.pbData)


def _saved_payload() -> dict[str, Any]:
    if not CREDENTIALS_PATH.exists():
        return {}
    try:
        payload = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def saved_credentials() -> tuple[str | None, str | None]:
    payload = _saved_payload()
    username = str(payload.get("username") or "").strip() or None
    protected = str(payload.get("api_key_dpapi") or "").strip()
    if not protected:
        return username, None
    try:
        return username, _unprotect(protected)
    except Exception:
        return username, None


def effective_credentials() -> tuple[str | None, str | None, str]:
    saved_username, saved_api_key = saved_credentials()
    env_username = os.environ.get("DANBOORU_USERNAME", "").strip()
    env_api_key = os.environ.get("DANBOORU_API_KEY", "").strip()
    username = env_username or saved_username
    api_key = env_api_key or saved_api_key
    source = "environment" if env_username or env_api_key else ("saved" if username or api_key else "none")
    return username, api_key, source


def credentials_status() -> dict[str, Any]:
    username, api_key, source = effective_credentials()
    saved_username, saved_api_key = saved_credentials()
    return {
        "username": username,
        "has_api_key": bool(api_key),
        "has_saved_api_key": bool(saved_api_key),
        "has_saved_credentials": bool(saved_username and saved_api_key),
        "configured": bool(username and api_key),
        "source": source,
    }


def save_credentials(username: str, api_key: str | None = None) -> dict[str, Any]:
    username = username.strip()
    _, saved_api_key = saved_credentials()
    api_key = api_key.strip() if api_key is not None else saved_api_key
    if not username:
        raise ValueError("Danbooru username is required")
    if not api_key:
        raise ValueError("Danbooru API key is required")
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "username": username,
        "api_key_dpapi": _protect(api_key),
        "saved_at": datetime.now().astimezone().isoformat(),
    }
    temporary = CREDENTIALS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(CREDENTIALS_PATH)
    return credentials_status()


def clear_credentials() -> dict[str, Any]:
    CREDENTIALS_PATH.unlink(missing_ok=True)
    return credentials_status()


def credential_environment() -> dict[str, str]:
    environment = dict(os.environ)
    username, api_key, _ = effective_credentials()
    if username:
        environment["DANBOORU_USERNAME"] = username
    if api_key:
        environment["DANBOORU_API_KEY"] = api_key
    return environment
