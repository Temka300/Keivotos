"""Synthetic local artwork for populated UI checks; never touches a real library."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from PIL import Image, ImageDraw


def seed_library(home: Path) -> None:
    assert home.parent.name.startswith('keivotos-modularization-') and home.name == 'home'
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
    from modules.danbooru.schema import ensure_data_schema

    media = home / 'artwork'
    metadata = home / 'modules' / 'danbooru'
    media.mkdir()
    metadata.mkdir(parents=True)
    (home / 'config.json').write_text(json.dumps({
        'default_library_created': True, 'data_root': str(media),
        'metadata_dir': str(metadata),
    }))
    with sqlite3.connect(metadata / 'danbooru.sqlite') as db:
        ensure_data_schema(db)
        for tag_id in range(1, 25):
            category = ('character', 'artist', 'copyright', 'general')[(tag_id - 1) % 4]
            db.execute('INSERT INTO tags VALUES (?, ?, ?)', (tag_id, f'fixture_{category}_{tag_id}', category))
        for ident in range(1, 49):
            image = Image.new('RGB', (960, 540), ((ident * 37) % 255, (ident * 61) % 255, (ident * 83) % 255))
            ImageDraw.Draw(image).text((40, 40), f'Keivotos browser fixture {ident}', fill='white')
            file = media / f'fixture-{ident:02}.jpg'
            image.save(file)
            db.execute('INSERT INTO files (id,path,folder,name,ext,size,local_md5,downloaded_at) VALUES (?,?,?,?,?,?,?,?)',
                       (ident, str(file), '', file.name, 'jpg', file.stat().st_size,
                        hashlib.md5(file.read_bytes()).hexdigest(), '2026-01-01T12:00:00'))
            db.execute('INSERT INTO posts (id,file_id,rating,score,created_at,width,height,file_ext) VALUES (?,?,?,?,?,?,?,?)',
                       (ident, ident, 'g', ident * 10, '2026-01-01T12:00:00', 960, 540, 'jpg'))
            for offset in range(4):
                db.execute('INSERT INTO post_tags VALUES (?, ?)', (ident, ((ident - 1) % 6) * 4 + offset + 1))
