"""Shared maintenance exclusion and the active tool reservation.

Danbooru retains its task registry; these locks coordinate it with suite backups.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager


_tool_state_lock = threading.RLock()
_tool_operation_lock = threading.RLock()
_active_tool_id: str | None = None


def active_tool_id() -> str | None:
    """Return the live tool owner while holding the shared state lock."""
    with _tool_state_lock:
        return _active_tool_id


@contextmanager
def exclusive_tool_operation(operation_name: str):
    """Prevent a restore/backup window from racing a newly launched tool."""
    with _tool_operation_lock:
        with _tool_state_lock:
            if _active_tool_id:
                raise RuntimeError(f"Wait for {_active_tool_id} to finish before {operation_name}")
        yield
