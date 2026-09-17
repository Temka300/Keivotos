"""Shared SQLite connections and the exclusive restore access gate."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator


class _DatabaseAccessGate:
    """Allow concurrent requests while giving restore a truly exclusive window."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._readers = 0
        self._writer_thread: int | None = None
        self._writer_depth = 0
        self._waiting_writers = 0

    @contextmanager
    def read(self) -> Generator[None, None, None]:
        thread_id = threading.get_ident()
        with self._condition:
            while (
                self._writer_thread not in (None, thread_id)
                or (self._waiting_writers > 0 and self._writer_thread != thread_id)
            ):
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @contextmanager
    def write(self) -> Generator[None, None, None]:
        thread_id = threading.get_ident()
        with self._condition:
            if self._writer_thread == thread_id:
                self._writer_depth += 1
            else:
                self._waiting_writers += 1
                try:
                    while self._writer_thread is not None or self._readers > 0:
                        self._condition.wait()
                    self._writer_thread = thread_id
                    self._writer_depth = 1
                finally:
                    self._waiting_writers -= 1
        try:
            yield
        finally:
            with self._condition:
                self._writer_depth -= 1
                if self._writer_depth == 0:
                    self._writer_thread = None
                    self._condition.notify_all()


_database_access_gate = _DatabaseAccessGate()


@contextmanager
def exclusive_database_access() -> Generator[None, None, None]:
    """Block new DB users and wait for live request connections to close."""
    with _database_access_gate.write():
        yield


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    columns = [col[0] for col in cursor.description]
    return dict(zip(columns, row))


@contextmanager
def connect_database(path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    with _database_access_gate.read():
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = _row_factory
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()
