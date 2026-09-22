"""Closed URL/quality inputs and explicit local engine detection."""
import importlib.util
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

VIDEO = ('best', '1080', '720', '480', 'audio')
AUDIO = ('best', '192', '128')


def canonical_url(value):
    try:
        url = urlsplit(value.strip())
        if url.scheme != 'https' or url.username or url.password or url.port not in (None,443):
            raise ValueError()
        host = (url.hostname or '').lower()
        if host == 'youtu.be':
            video = url.path.strip('/')
        elif host in ('youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'):
            if url.path == '/watch':
                video = parse_qs(url.query).get('v',[''])[0]
            elif url.path.startswith(('/shorts/','/live/','/embed/')):
                video = url.path.split('/')[2]
            else:
                raise ValueError()
        else:
            raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
            raise ValueError()
        return 'https://www.youtube.com/watch?v='+video
    except (ValueError,IndexError):
        raise ValueError('Enter a YouTube video URL (https). Playlists are not supported.') from None


def format_selector(video, audio):
    if video not in VIDEO or audio not in AUDIO:
        raise ValueError('Unknown quality selection')
    sound = 'bestaudio' + (f'[abr<={audio}]' if audio != 'best' else '')
    if video == 'audio':
        return sound
    height = f'[height<={video}]' if video != 'best' else ''
    audio_limit = f'[abr<={audio}]' if audio != 'best' else ''
    return f'bestvideo{height}+{sound}/best{height}{audio_limit}'


def dependencies():
    missing=[]
    for package in ('yt_dlp',):
        if importlib.util.find_spec(package) is None:missing.append(package.replace('_','-'))
    ffmpeg = None
    if getattr(sys,'frozen',False):
        candidate=Path(sys.executable).parent/('ffmpeg.exe' if sys.platform=='win32' else 'ffmpeg')
        if candidate.is_file():ffmpeg=str(candidate)
    else:
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:
            try:
                import imageio_ffmpeg
                ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
            except (ImportError,RuntimeError):pass
    if not ffmpeg:missing.append('FFmpeg')
    return {'ready':not missing,'missing':missing,'ffmpeg':ffmpeg}
