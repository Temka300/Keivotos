"""Local chapter discovery and bounded ZIP/image reads; never extract originals."""
from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import struct
import warnings
import zipfile

from PIL import Image, ImageOps
from files_base import index, serving
from modules.manga.page_cache import PageData, file_identity, manifests, responses

IMAGES = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'avif'}
ARCHIVES = {'zip', 'cbz'}
MAX_ENTRIES = 4096
MAX_PAGE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_PIXELS = 24_000_000
RENDER_VERSION = 'manga-v1'
ORIGINAL_MIMES = {'JPEG': 'image/jpeg', 'PNG': 'image/png',
                  'GIF': 'image/gif', 'WEBP': 'image/webp'}


class OriginalUnavailable(ValueError):
    """A raster needs explicit conversion rather than original-byte delivery."""


class StaleRevision(ValueError):
    pass


def natural(value):
    # Tagged parts keep mixed digit/text names comparable; spelling breaks ties.
    return ([(1, int(p)) if p.isdigit() else (0, p.casefold())
             for p in re.split(r'(\d+)', value)], value)


def catalog(db, owners):
    groups = {}
    with index.open_index(db) as connection:
        for source in owners:
            rows = connection.execute(
                'SELECT relative_path, ext FROM files_index WHERE source_id=? AND is_dir=0 AND available=1',
                (source.source_id,))
            for row in rows:
                ext = row['ext']
                if ext not in IMAGES | ARCHIVES:
                    continue
                path = PurePosixPath(row['relative_path'])
                parent = path.parent
                # Each top-level folder is a series. Root pages/archives belong
                # to the source itself, permitting a single-series source too.
                series = path.parts[0] if len(path.parts) > 1 else ''
                chapter = str(path) if ext in ARCHIVES else (str(parent) if str(parent) != '.' else '')
                kind = 'archive' if ext in ARCHIVES else 'folder'
                group = groups.setdefault((source.source_id, series), {
                    'source_id': source.source_id, 'path': series,
                    'name': series or source.display_name, 'chapters': {}})
                label = str(PurePosixPath(chapter).relative_to(series)) if series else chapter
                if kind == 'archive':
                    label = str(PurePosixPath(label).with_suffix(''))
                group['chapters'][(kind, chapter)] = {
                    'path': chapter, 'kind': kind, 'name': label if label not in ('', '.') else 'Chapter 1'}
    result = []
    for group in groups.values():
        group['chapters'] = sorted(group['chapters'].values(), key=lambda c: natural(c['name']))
        result.append(group)
    return sorted(result, key=lambda g: (natural(g['name']), g['source_id'], g['path']))


def chapter_exists(db, source_id, chapter, kind):
    extensions = ARCHIVES if kind == 'archive' else IMAGES
    column = 'relative_path' if kind == 'archive' else 'parent'
    marks = ','.join('?' for _ in extensions)
    with index.open_index(db) as connection:
        return connection.execute(
            f'SELECT 1 FROM files_index WHERE source_id=? AND {column}=? '
            f'AND is_dir=0 AND available=1 AND ext IN ({marks}) LIMIT 1',
            (source_id, chapter, *extensions)).fetchone() is not None


def folder_pages(db, source_id, chapter):
    with index.open_index(db) as connection:
        rows = connection.execute(
            'SELECT relative_path,ext FROM files_index WHERE source_id=? AND parent=? AND is_dir=0 AND available=1',
            (source_id, chapter))
        pages = [r['relative_path'] for r in rows if r['ext'] in IMAGES
                 and str(PurePosixPath(r['relative_path']).parent) == (chapter or '.')]
    if len(pages) > MAX_ENTRIES:
        raise ValueError('Chapter has too many pages')
    # Query the current indexed listing each time: a rescan must invalidate
    # even when the directory name and all filesystem timestamps stay the same.
    scope = ('folder', str(Path(db).resolve()), source_id, chapter)
    revision = frozenset(pages)
    cached = manifests.get(scope, revision)
    if cached is None:
        cached = tuple(sorted(pages, key=natural))
        manifests.put(scope, revision, cached)
    return list(cached)


def _directory_identity(file):
    # Bound the central directory BEFORE ZipFile allocates its member objects.
    # ZIP64 and split archives are deliberately unsupported in this basic reader.
    file.seek(0, 2)
    size = file.tell()
    file.seek(max(0, size - 65557))
    tail = file.read(65557)
    start = tail.rfind(b'PK\x05\x06')
    if start < 0 or len(tail) - start < 22:
        raise ValueError('Invalid ZIP directory')
    _, disk, directory_disk, disk_count, count, directory_size, offset, comment = struct.unpack_from('<4s4H2LH', tail, start)
    if (disk or directory_disk or disk_count != count or count > MAX_ENTRIES
            or directory_size > 16 * 1024 * 1024 or offset == 0xffffffff
            or start + 22 + comment != len(tail) or b'PK\x06\x07' in tail[max(0,start-20):start]):
        raise ValueError('Unsupported or oversized ZIP directory')
    # The actual directory ends at the EOCD, allowing the same prepended ZIP
    # data that ZipFile supports. Hash it so restored mtimes cannot reuse an
    # old validation for changed entry names, flags, sizes or checksums.
    directory_start = size - len(tail) + start - directory_size
    if directory_start < 0:
        raise ValueError('Invalid ZIP directory')
    file.seek(directory_start)
    directory = file.read(directory_size)
    if len(directory) != directory_size:
        raise ValueError('Invalid ZIP directory')
    return sha256(directory + tail[start:]).digest()


def _validate_archive(archive):
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ValueError('Too many archive entries')
    names = set()
    total = 0
    pages = []
    for info in infos:
        name = info.filename
        original_name = info.orig_filename
        parts = name.rstrip('/').split('/')
        mode = info.external_attr >> 16
        if (not name or '\\' in original_name or '\x00' in original_name
                or PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive
                or any(p in ('', '.', '..') for p in parts)
                or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                or name.casefold() in names or info.flag_bits & 1
                or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise ValueError('Unsafe or encrypted archive entry')
        names.add(name.casefold())
        total += info.file_size
        if (info.file_size > MAX_PAGE_BYTES or total > MAX_TOTAL_BYTES
                or info.file_size > max(1, info.compress_size) * 1000):
            raise ValueError('Archive expansion limit exceeded')
        if not info.is_dir() and PurePosixPath(name).suffix.lower().lstrip('.') in IMAGES:
            pages.append(info)
    return sorted(pages, key=lambda info: natural(info.filename))


def _assert_unchanged(path, file, identity):
    if (file_identity(os.fstat(file.fileno())) != identity
            or file_identity(path.stat()) != identity or path.resolve() != path):
        raise ValueError('Chapter changed while being read; reopen it')


@contextmanager
def open_archive(path, source_id=None):
    path = Path(path).absolute()
    scope = ('archive', source_id, str(path))
    with path.open('rb') as file:
        identity = file_identity(os.fstat(file.fileno()))
        directory = _directory_identity(file)
        revision = (identity, directory, MAX_ENTRIES, MAX_PAGE_BYTES, MAX_TOTAL_BYTES)
        cached = manifests.get(scope, revision) if source_id is not None else None
        _assert_unchanged(path, file, identity)
        file.seek(0)
        with zipfile.ZipFile(file) as archive:
            pages = _validate_archive(archive) if cached is None else [archive.getinfo(name) for name in cached]
            _assert_unchanged(path, file, identity)
            try:
                yield archive, pages
            finally:
                try:
                    _assert_unchanged(path, file, identity)
                except (ValueError, OSError):
                    manifests.discard(scope)
                    raise
            if cached is None and source_id is not None:
                manifests.put(scope, revision, (info.filename for info in pages))


def render_page(raw, cover=False):
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValueError('Image dimensions exceed reader limit')
            image.seek(0)
            image = ImageOps.exif_transpose(image)
            image.thumbnail((480, 720) if cover else (2400, 3600))
            output = BytesIO()
            image.convert('RGB').save(output, 'WEBP', quality=85)
            return output.getvalue()


def _revision(source, target, identity, member=None):
    values = (source.source_id, str(target), identity, member)
    return sha256(repr(values).encode('utf-8', errors='surrogatepass')).hexdigest()


def _archive_revision(source, target, archive, info):
    identity = file_identity(os.fstat(archive.fp.fileno()))
    member = (info.filename, info.CRC, info.file_size, info.compress_size,
              info.header_offset, info.flag_bits, info.compress_type)
    return _revision(source, target, identity, member)


def chapter_metadata(source, chapter, kind, db, forbidden, first_only=False):
    target = serving.resolve_within_source(source.path, chapter, forbidden)
    if kind == 'archive':
        with open_archive(target, source_id=source.source_id) as (archive, pages):
            revisions = [_archive_revision(source, target, archive, info)
                         for info in (pages[:1] if first_only else pages)]
    else:
        revisions = []
        names = folder_pages(db, source.source_id, chapter)
        for name in (names[:1] if first_only else names):
            try:
                page = serving.resolve_served_file(source.path, name, forbidden)
                revisions.append(_revision(source, page, file_identity(page.stat())))
            except (OSError, serving.ServeDenied):
                # Preserve discovery of other pages. The actual read still
                # refuses missing, protected or outside targets through serving.
                revisions.append(_revision(source, target, None, name))
    return {'count': len(revisions), 'revisions': revisions,
            'revision': sha256(''.join(revisions).encode()).hexdigest()}


def read_page_bytes(source, chapter, kind, page, db, forbidden, revision=None):
    target = serving.resolve_within_source(source.path, chapter, forbidden)
    if kind == 'archive':
        with open_archive(target, source_id=source.source_id) as (archive, pages):
            if page >= len(pages):
                raise IndexError('Page is unavailable')
            current = _archive_revision(source, target, archive, pages[page])
            if revision is not None and revision != current:
                raise StaleRevision('Chapter changed; reopen it to load the current pages')
            with archive.open(pages[page]) as stream:
                raw = stream.read(MAX_PAGE_BYTES + 1)
    else:
        pages = folder_pages(db, source.source_id, chapter)
        if page >= len(pages):
            raise IndexError('Page is unavailable')
        target = serving.resolve_served_file(source.path, pages[page], forbidden)
        with target.open('rb') as stream:
            identity = file_identity(os.fstat(stream.fileno()))
            _assert_unchanged(target, stream, identity)
            current = _revision(source, target, identity)
            if revision is not None and revision != current:
                raise StaleRevision('Chapter changed; reopen it to load the current pages')
            raw = stream.read(MAX_PAGE_BYTES + 1)
            _assert_unchanged(target, stream, identity)
    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError('Page exceeds reader limit')
    return raw, current


def original_page(raw):
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValueError('Image dimensions exceed reader limit')
            media_type = ORIGINAL_MIMES.get(image.format)
            if media_type is None:
                raise OriginalUnavailable('This image format needs conversion')
            if getattr(image, 'is_animated', False):
                raise OriginalUnavailable('Animated pages need conversion to a still image')
            image.verify()
        # verify() checks structure; a full decode also refuses truncated data.
        # The original bytes (including valid EXIF orientation) are preserved.
        with Image.open(BytesIO(raw)) as image:
            if image.getexif().get(274, 1) not in range(1, 9):
                raise OriginalUnavailable('This page has unsupported orientation metadata')
            image.load()
    return PageData(raw, media_type)


def page_response(source, chapter, kind, page, db, forbidden, cover=False,
                  representation='webp', revision=None):
    raw, current = read_page_bytes(source, chapter, kind, page, db, forbidden, revision)
    digest = sha256(raw).hexdigest()
    variant = 'cover' if cover else representation
    key = (RENDER_VERSION, digest, variant, (480, 720) if cover else (2400, 3600),
           85, MAX_PIXELS, MAX_PAGE_BYTES)
    if cover:
        from thumbnails import derived_thumbnail_bytes
        content = derived_thumbnail_bytes(repr(key), lambda: render_page(raw, True))
        result = PageData(content, 'image/webp')
    else:
        result = responses.get_or_create(key, lambda: original_page(raw) if representation == 'original'
                                        else PageData(render_page(raw), 'image/webp'))
    return result, current


def read_page(source, chapter, kind, page, db, forbidden, cover=False):
    # Existing callers retain WebP defaults; the new reader opts into Original.
    return page_response(source, chapter, kind, page, db, forbidden, cover)[0].content
