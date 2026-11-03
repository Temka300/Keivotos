"""Paginated directory facts from Files; no decoding, tagging or media writes."""
import os
from pathlib import Path
import re

from files_base import index, serving, sources

# Consume Files' closed audio MIME allowlist, rather than inventing codec support.
AUDIO_EXTENSIONS = tuple(serving._INLINE_AUDIO)


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
    items = [{'source_id': source.source_id, 'path': row['relative_path'],
              'name': row['name'], 'ext': row['ext'], 'is_dir': bool(row['is_dir']),
              'size': row['size'], 'mtime': row['mtime'],
              'available': available(source, row['relative_path'], bool(row['is_dir']), forbidden)}
             for row in rows]
    return {'source_id': source.source_id, 'parent': relative, 'items': items, 'total': total}
