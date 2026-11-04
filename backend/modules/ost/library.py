"""Paginated directory facts from Files; no decoding, tagging or media writes."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re

from files_base import index, serving, sources

# Consume Files' closed audio MIME allowlist, rather than inventing codec support.
AUDIO_EXTENSIONS = tuple(serving._INLINE_AUDIO)
COVER_NAMES = ('cover', 'folder', 'front')
COVER_EXTENSIONS = ('jpg', 'jpeg', 'png', 'webp')
COVER_FILES = tuple(f'{name}.{ext}' for name in COVER_NAMES for ext in COVER_EXTENSIONS)


def _natural(value: str):
    return ([(1, int(part)) if part.isdecimal() else (0, part.casefold())
             for part in re.split(r'(\d+)', value)], value)


def forbidden_roots(source, all_sources, suite_home):
    return [Path(suite_home), *(Path(child.path)
            for child in sources.descendant_sources(source, all_sources))]


def directory_path(source, parent, forbidden):
    target = serving.resolve_within_source(source.path, parent, forbidden)
    if not target.is_dir():
        raise serving.ServeDenied(404, "OST folder is unavailable")
    return target


def available(source, path, is_dir, forbidden):
    try:
        target = serving.resolve_within_source(source.path, path, forbidden)
        return target.is_dir() if is_dir else target.is_file()
    except (serving.ServeDenied, OSError, ValueError):
        return False


def named_covers(connection, source, parent, forbidden):
    """At most twelve same-folder candidates; index facts, then fresh guards."""
    marks = ','.join('?' for _ in COVER_FILES)
    priority = ' '.join(f'WHEN ? THEN {rank}' for rank in range(len(COVER_FILES)))
    rows = connection.execute(
        f'SELECT relative_path FROM files_index WHERE source_id=? AND parent=? '
        f'AND available=1 AND is_dir=0 AND LOWER(name) IN ({marks}) '
        f'ORDER BY CASE LOWER(name) {priority} END,name LIMIT ?',
        [source.source_id, parent, *COVER_FILES, *COVER_FILES, len(COVER_FILES)]).fetchall()
    candidates = []
    for row in rows:
        try:
            target = serving.resolve_within_source(source.path, row['relative_path'], forbidden)
            if target.is_file():
                candidates.append(target)
        except (serving.ServeDenied, OSError, ValueError):
            continue
    return candidates


def cover_version(connection, source, path, is_dir, forbidden, folders=None):
    """A cheap revision of the subject and its local fallback art; no decoding."""
    folders = {} if folders is None else folders
    try:
        target = serving.resolve_within_source(source.path, path, forbidden)
        stat = target.stat()
        relative = target.relative_to(Path(source.path).resolve()).as_posix()
        parent = relative if is_dir else str(PurePosixPath(relative).parent)
        parent = '' if parent == '.' else parent
        if parent not in folders:
            facts = []
            for candidate in named_covers(connection, source, parent, forbidden):
                try:
                    identity = candidate.stat()
                    facts.append((str(candidate), identity.st_mtime_ns, identity.st_size))
                except OSError:
                    continue
            folders[parent] = facts
        facts = [path, stat.st_mtime_ns, stat.st_size, folders[parent]]
        return hashlib.sha256(json.dumps(facts).encode()).hexdigest()[:24]
    except (serving.ServeDenied, OSError, ValueError):
        return 'unavailable'


def cover_file(db, source, all_sources, suite_home, path, size):
    """Reuse the thumbnail engine: embedded art, named local art, deliberate miss."""
    from routers.files import _thumbnail_cache_key
    from thumbnails import ensure_thumbnail

    forbidden = forbidden_roots(source, all_sources, suite_home)
    target = serving.resolve_within_source(source.path, path, forbidden)
    is_dir = target.is_dir()
    if not is_dir and (not target.is_file() or target.suffix.lower().lstrip('.') not in AUDIO_EXTENSIONS):
        raise serving.ServeDenied(404, 'OST cover is unavailable')
    relative = target.relative_to(Path(source.path).resolve()).as_posix()
    parent = relative if is_dir else str(PurePosixPath(relative).parent)
    parent = '' if parent == '.' else parent
    with index.open_index(db) as connection:
        candidates = ([] if is_dir else [target]) + named_covers(connection, source, parent, forbidden)
    for candidate in candidates:
        key = _thumbnail_cache_key(candidate)
        if key is None:
            continue
        thumb = ensure_thumbnail(str(candidate), size, key)
        if thumb is not None and thumb.is_file():
            return thumb
    raise serving.ServeDenied(404, 'OST cover is unavailable')


def directory(db, source, all_sources, suite_home, parent, offset, limit):
    forbidden = forbidden_roots(source, all_sources, suite_home)
    target = directory_path(source, parent, forbidden)
    root = Path(source.path).resolve()
    relative = target.relative_to(root).as_posix()
    relative = '' if relative == '.' else relative
    excluded = [os.path.normcase(Path(os.path.relpath(path, root)).as_posix())
                for path in forbidden if sources.is_strict_descendant_path(path, root)]

    def owned(path):
        path = os.path.normcase(path)
        return not any(path == child or path.startswith(child + os.path.normcase('/'))
                       for child in excluded)

    def compare(left, right):
        a, b = _natural(left), _natural(right)
        return (a > b) - (a < b)

    marks = ','.join('?' for _ in AUDIO_EXTENSIONS)
    where = (f'source_id=? AND parent=? AND available=1 '
             f'AND (is_dir=1 OR ext IN ({marks})) AND ost_owned(relative_path)')
    parameters = [source.source_id, relative, *AUDIO_EXTENSIONS]
    with index.open_index(db) as connection:
        connection.create_collation('ost_natural', compare)
        connection.create_function('ost_owned', 1, owned)
        total = connection.execute(f'SELECT count(*) FROM files_index WHERE {where}', parameters).fetchone()[0]
        rows = connection.execute(
            f'SELECT relative_path,name,ext,is_dir,size,mtime FROM files_index WHERE {where} '
            'ORDER BY is_dir DESC,name COLLATE ost_natural,relative_path LIMIT ? OFFSET ?',
            [*parameters, limit, offset]).fetchall()
        folders = {}
        items = [{'source_id': source.source_id, 'path': row['relative_path'],
                  'name': row['name'], 'ext': row['ext'], 'is_dir': bool(row['is_dir']),
                  'size': row['size'], 'mtime': row['mtime'],
                  'available': available(source, row['relative_path'], bool(row['is_dir']), forbidden),
                  'cover_version': cover_version(connection, source, row['relative_path'],
                                                 bool(row['is_dir']), forbidden, folders)}
                 for row in rows]
    return {'source_id': source.source_id, 'parent': relative, 'items': items, 'total': total}
