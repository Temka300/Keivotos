"""Generated audio and local artwork; no downloads, credentials or user media."""
from io import BytesIO
import math
from pathlib import Path
import struct
import subprocess
import wave

from PIL import Image, ImageDraw, ImageFont


def write_audio(path: Path, seconds=4):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        # A small generated tone is also suitable for later transport checks.
        period = b''.join(struct.pack('<h', int(2000 * math.sin(2 * math.pi * 440 * n / 8000)))
                          for n in range(8000))
        audio.writeframes(period * seconds)


def artwork(title, background='#263f59', accent='#83bedc'):
    image = Image.new('RGB', (400, 400), background)
    draw = ImageDraw.Draw(image)
    for offset in (0, 24, 48):
        draw.ellipse((90 + offset, 68 + offset, 370 - offset, 348 - offset), outline=accent, width=2)
    draw.ellipse((205, 182, 255, 232), fill=accent)
    for n in range(26):
        height = 14 + int(32 * abs(math.sin(n * .55)))
        draw.line((24 + n * 6, 275 - height, 24 + n * 6, 275 + height), fill=accent, width=2)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 27)
        small = ImageFont.truetype('DejaVuSans.ttf', 13)
    except OSError:
        font = ImageFont.load_default(size=27)
        small = ImageFont.load_default(size=13)
    draw.text((22, 24), 'LOCAL OST', font=small, fill=accent)
    draw.text((22, 337), title, font=font, fill='#f5f2ea')
    data = BytesIO()
    image.save(data, 'PNG')
    return data.getvalue()


def embedded_audio(path: Path, picture: Path):
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'anullsrc=r=8000:cl=mono', '-i', str(picture),
                    '-map', '0:a', '-map', '1:v', '-c:a', 'flac', '-c:v', 'copy',
                    '-disposition:v', 'attached_pic', '-t', '4', str(path)], check=True, timeout=30)


LONG_TRACK = 'A long soundtrack title with quiet rain and a distant train that wraps across two rows while its complete name remains readable 曲 2.wav'


def seed_ost(media: Path):
    media.mkdir()
    albums = ('Album 2', 'Album 10', 'Corrupt art', 'Empty', 'Large library', 'No art')
    for name in albums:
        (media / name).mkdir()
    (media / 'Album 2/Cover.JPG').write_bytes(artwork('BLUE HOURS'))
    (media / 'Album 2/folder.png').write_bytes(artwork('SECOND', '#32523f', '#a3d4ad'))
    (media / 'Album 2/front.webp').write_bytes(artwork('THIRD', '#553a53', '#d2a8d0'))
    embedded = media / 'Album 2/embedded-picture.png'
    embedded.write_bytes(artwork('FIRST LIGHT', '#725034', '#edc68a'))
    embedded_audio(media / 'Album 2/00 - Opening.flac', embedded)
    for name in ('Track 2.wav', 'Track 10.wav', LONG_TRACK):
        write_audio(media / 'Album 2' / name, seconds=20)
    write_audio(media / 'Album 2/Deep/曲 2.wav')
    (media / 'Album 10/folder.PNG').write_bytes(artwork('TEN', '#725034', '#edc68a'))
    write_audio(media / 'Album 10/Track 2.wav')
    (media / 'Corrupt art/cover.jpg').write_bytes(b'generated corrupt artwork')
    (media / 'Corrupt art/folder.png').write_bytes(artwork('RECOVERY', '#553a53', '#d2a8d0'))
    write_audio(media / 'Corrupt art/Track 2.wav')
    write_audio(media / 'No art/Track 2.wav')
    (media / 'No art/broken.mp3').write_bytes(b'generated invalid audio')
    (media / 'No art/unsupported.aac').write_bytes(b'generated unsupported extension')
    (media / 'No art/note.txt').write_text('Generated only. Not a track.\n')
    (media / 'Large library/cover.png').write_bytes(artwork('LOCAL COLLECTION'))
    for number in range(1, 261):
        write_audio(media / 'Large library' / f'Track {number}.wav')
    write_audio(media / 'Root track.wav')
