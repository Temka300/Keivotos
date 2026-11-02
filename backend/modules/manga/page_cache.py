"""Bounded Manga page-name manifests; no media bytes or open file handles."""
from collections import OrderedDict
from dataclasses import dataclass
import os
from threading import RLock


def file_identity(info):
    # Windows stat/fstat can report different creation times for one unchanged
    # file. Keep POSIX change time; archive directory digests also catch rewrites
    # whose size and modification time were deliberately restored.
    changed = None if os.name == 'nt' else info.st_ctime_ns
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, changed)


@dataclass(frozen=True)
class Manifest:
    revision: object
    pages: tuple[str, ...]
    name_bytes: int


class ManifestCache:
    def __init__(self, max_entries=64, max_pages=16384, max_name_bytes=4 * 1024 * 1024):
        self.max_entries = max_entries
        self.max_pages = max_pages
        self.max_name_bytes = max_name_bytes
        self._items = OrderedDict()
        self._pages = 0
        self._name_bytes = 0
        self._lock = RLock()

    def _remove(self, scope):
        previous = self._items.pop(scope, None)
        if previous:
            self._pages -= len(previous.pages)
            self._name_bytes -= previous.name_bytes

    def get(self, scope, revision):
        with self._lock:
            item = self._items.get(scope)
            if item is None:
                return None
            if item.revision != revision:
                self._remove(scope)
                return None
            self._items.move_to_end(scope)
            return item.pages

    def put(self, scope, revision, pages):
        pages = tuple(pages)
        size = sum(len(name.encode('utf-8', errors='surrogatepass')) for name in pages)
        with self._lock:
            self._remove(scope)
            if len(pages) > self.max_pages or size > self.max_name_bytes:
                return
            self._items[scope] = Manifest(revision, pages, size)
            self._pages += len(pages)
            self._name_bytes += size
            while (len(self._items) > self.max_entries or self._pages > self.max_pages
                   or self._name_bytes > self.max_name_bytes):
                self._remove(next(iter(self._items)))

    def discard(self, scope):
        with self._lock:
            self._remove(scope)

    def clear(self):
        with self._lock:
            self._items.clear()
            self._pages = self._name_bytes = 0


manifests = ManifestCache()
