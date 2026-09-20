"""Shared maintenance exclusion and the active tool reservation.

Danbooru retains its task registry; these locks coordinate it with suite backups.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager


_tool_state_lock = threading.RLock()
_tool_operation_lock = threading.RLock()
_active_tool_id: str | None = None
_module_transition = False
_module_operations = 0


def active_tool_id() -> str | None:
    """Return the live tool owner while holding the shared state lock."""
    with _tool_state_lock:
        return _active_tool_id


@contextmanager
def exclusive_tool_operation(operation_name: str, *, wait: bool = True):
    """Prevent a restore/backup window from racing a newly launched tool."""
    if not _tool_operation_lock.acquire(blocking=wait):
        raise RuntimeError("Another maintenance operation is running")
    try:
        if _module_transition:
            raise RuntimeError("Wait for the module transition to finish")
        with _tool_state_lock:
            if _active_tool_id:
                raise RuntimeError(f"Wait for {_active_tool_id} to finish before {operation_name}")
        yield
    finally:
        _tool_operation_lock.release()


@contextmanager
def module_transition():
    """Reserve live toggles without holding a thread lock while workers drain."""
    global _module_transition
    if not _tool_operation_lock.acquire(blocking=False):
        raise RuntimeError("Wait for maintenance to finish before changing modules")
    try:
        if _module_transition:
            raise RuntimeError("Wait for the module transition to finish")
        if _module_operations:
            raise RuntimeError("Wait for module operations to finish before changing modules")
        with _tool_state_lock:
            if _active_tool_id:
                raise RuntimeError(f"Wait for {_active_tool_id} to finish before changing modules")
        _module_transition = True
    finally:
        _tool_operation_lock.release()
    try:
        yield
    finally:
        with _tool_operation_lock:
            _module_transition = False


@contextmanager
def module_operation():
    """Keep a live transition from racing an admitted module request."""
    global _module_operations
    with _tool_operation_lock:
        if _module_transition:
            raise RuntimeError("Wait for the module transition to finish")
        _module_operations += 1
    try:
        yield
    finally:
        with _tool_operation_lock:
            _module_operations -= 1
