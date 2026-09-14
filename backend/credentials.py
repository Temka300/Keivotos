"""Local Danbooru credentials: Windows DPAPI and Linux Secret Service."""
from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import uuid
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


# Keep all key material on stdin/stdout, never on a command line. A subprocess
# bounds D-Bus failures without leaving blocked request/background threads.
_VAULT_WORKER = r"""
import json, sys
try:
    import secretstorage
    from keyring.backends.SecretService import Keyring
    class UnlockedKeyring(Keyring):
        def get_preferred_collection(self):
            connection = secretstorage.dbus_init()
            try:
                collection = secretstorage.Collection(connection, '/org/freedesktop/secrets/aliases/default')
                if collection.is_locked():
                    raise RuntimeError('locked')
                return collection
            except Exception:
                connection.close()
                raise
        def unlock(self, item):
            if item.is_locked():
                raise RuntimeError('locked')
    request = json.load(sys.stdin)
    vault = UnlockedKeyring()
    service, reference = 'Keivotos Danbooru', request['reference']
    operation = request['operation']
    value = None
    if operation == 'get':
        value = vault.get_password(service, reference)
    elif operation == 'set':
        vault.set_password(service, reference, request['secret'])
    elif operation == 'delete':
        if vault.get_password(service, reference) is not None:
            vault.delete_password(service, reference)
    else:
        raise ValueError('invalid operation')
    print(json.dumps({'value': value}))
except Exception:
    # Exceptions from providers are not trusted to omit key material.
    print(json.dumps({'error': True}))
"""
_VAULT_ERROR = (
    "Linux credential vault is unavailable, locked, or did not respond. "
    "Start and unlock a Secret Service vault (such as GNOME Keyring) in the "
    "same desktop/D-Bus session, or use DANBOORU_USERNAME and DANBOORU_API_KEY."
)
_credential_lock = threading.RLock()
_logger = logging.getLogger(__name__)


def _uses_linux_vault() -> bool:
    return sys.platform == "linux"


def _vault(operation: str, reference: str, secret: str | None = None) -> str | None:
    try:
        result = subprocess.run(
            ([sys.executable, "--credential-worker"] if getattr(sys, "frozen", False)
             else [sys.executable, "-c", _VAULT_WORKER]),
            input=json.dumps({"operation": operation, "reference": reference, "secret": secret}),
            capture_output=True, text=True, timeout=10,
        )
        payload = json.loads(result.stdout)
        if (
            result.returncode or payload.get("error") or "value" not in payload
            or not isinstance(payload["value"], (str, type(None)))
        ):
            raise ValueError("vault failed")
        return payload.get("value")
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
        raise RuntimeError(_VAULT_ERROR) from None


def _saved_payload() -> dict[str, Any]:
    if not CREDENTIALS_PATH.exists():
        return {}
    try:
        payload = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def saved_credentials(*, strict: bool = False) -> tuple[str | None, str | None]:
    # Keep the manifest reference and its secret together while save/clear
    # replaces or removes vault items. Status/save/clear may already hold this
    # reentrant lock; ordinary request/background reads must take it too.
    with _credential_lock:
        payload = _saved_payload()
        if _uses_linux_vault() and isinstance(payload.get("linux_secret_service"), dict):
            linux = payload["linux_secret_service"]
            username = str(linux.get("username") or "").strip() or None
            reference = str(linux.get("reference") or "")
            try:
                secret = _vault("get", reference)
                if not secret:
                    raise RuntimeError("Saved Linux credential is missing from the vault; enter the API key again.")
                return username, secret
            except RuntimeError:
                if strict:
                    raise
                return username, None
        username = str(payload.get("username") or "").strip() or None
        protected = str(payload.get("api_key_dpapi") or "").strip()
        if not protected:
            return username, None
        try:
            return username, _unprotect(protected)
        except Exception:
            return username, None


def _effective(saved: tuple[str | None, str | None]) -> tuple[str | None, str | None, str]:
    saved_username, saved_api_key = saved
    env_username = os.environ.get("DANBOORU_USERNAME", "").strip()
    env_api_key = os.environ.get("DANBOORU_API_KEY", "").strip()
    username = env_username or saved_username
    api_key = env_api_key or saved_api_key
    source = "environment" if env_username or env_api_key else ("saved" if username or api_key else "none")
    return username, api_key, source


def effective_credentials() -> tuple[str | None, str | None, str]:
    # A complete environment override works even when a vault is locked/offline.
    if os.environ.get("DANBOORU_USERNAME", "").strip() and os.environ.get("DANBOORU_API_KEY", "").strip():
        return _effective((None, None))
    return _effective(saved_credentials())


def credentials_status() -> dict[str, Any]:
    with _credential_lock:
        complete_override = bool(os.environ.get("DANBOORU_USERNAME", "").strip() and os.environ.get("DANBOORU_API_KEY", "").strip())
        saved = saved_credentials(strict=not complete_override)
        username, api_key, source = _effective(saved)
        return _status(username, api_key, source, saved)


def _status(
    username: str | None, api_key: str | None, source: str,
    saved: tuple[str | None, str | None],
) -> dict[str, Any]:
    saved_username, saved_api_key = saved
    return {
        "username": username,
        "has_api_key": bool(api_key),
        "has_saved_api_key": bool(saved_api_key),
        "has_saved_credentials": bool(saved_username and saved_api_key),
        "configured": bool(username and api_key),
        "source": source,
    }


def _write_payload(payload: dict[str, Any]) -> None:
    if not payload:
        CREDENTIALS_PATH.unlink(missing_ok=True)
        return
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CREDENTIALS_PATH.parent,
                                         prefix=".danbooru_credentials-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(payload, indent=2) + "\n")
        temporary.replace(CREDENTIALS_PATH)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_credentials(username: str, api_key: str | None = None) -> dict[str, Any]:
    with _credential_lock:
        username = username.strip()
        if not username:
            raise ValueError("Danbooru username is required")
        api_key = api_key.strip() if api_key is not None else saved_credentials(strict=True)[1]
        if not api_key:
            raise ValueError("Danbooru API key is required")
        payload = _saved_payload()
        if _uses_linux_vault():
            previous = payload.get("linux_secret_service", {})
            reference = uuid.uuid4().hex
            try:
                _vault("set", reference, api_key)
                if _vault("get", reference) != api_key:
                    raise RuntimeError("Linux credential vault could not verify the saved API key.")
                payload["linux_secret_service"] = {
                    "username": username, "reference": reference,
                    "saved_at": datetime.now().astimezone().isoformat(),
                }
                _write_payload(payload)
            except (RuntimeError, OSError):
                try:
                    _vault("delete", reference)
                except RuntimeError:
                    pass
                raise RuntimeError("Could not save Linux credentials. Existing saved credentials were preserved. " + _VAULT_ERROR) from None
            if isinstance(previous, dict) and previous.get("reference"):
                try:
                    _vault("delete", str(previous["reference"]))
                except RuntimeError:
                    _logger.warning("Credentials saved, but a superseded Linux vault item could not be removed.")
        else:
            payload.update({
                "username": username, "api_key_dpapi": _protect(api_key),
                "saved_at": datetime.now().astimezone().isoformat(),
            })
            _write_payload(payload)
        # The new key was verified already; do not turn a successful save into
        # an error if the vault becomes unavailable immediately afterwards.
        saved = (username, api_key)
        return _status(*_effective(saved), saved)


def clear_credentials() -> dict[str, Any]:
    with _credential_lock:
        payload = _saved_payload()
        if _uses_linux_vault():
            linux = payload.get("linux_secret_service")
            if isinstance(linux, dict) and linux.get("reference"):
                reference = str(linux["reference"])
                secret = _vault("get", reference)
                _vault("delete", reference)
                del payload["linux_secret_service"]
                try:
                    _write_payload(payload)
                except OSError:
                    if secret:
                        _vault("set", reference, secret)
                    raise RuntimeError("Could not update the credential file; retry clearing credentials.") from None
            # Preserve Windows DPAPI fields on Linux, even when no vault entry
            # exists. Switching platforms must not erase the other OS's key.
        else:
            for field in ("username", "api_key_dpapi", "saved_at"):
                payload.pop(field, None)
            _write_payload(payload)
        saved = saved_credentials()
        return _status(*_effective(saved), saved)


def credential_environment() -> dict[str, str]:
    environment = dict(os.environ)
    username, api_key, _ = effective_credentials()
    if username:
        environment["DANBOORU_USERNAME"] = username
    if api_key:
        environment["DANBOORU_API_KEY"] = api_key
    return environment
