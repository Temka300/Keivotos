"""Dedicated yt-dlp process: structured events, no app DB or shell command input."""
import json
import sys
import time
from pathlib import Path
from modules.youtube.engine import canonical_url, format_selector


def emit(**event):
    print(json.dumps(event,ensure_ascii=True),flush=True)


class Log:
    def debug(self,message):
        if not message.startswith('[debug]'):print(message,file=sys.stderr,flush=True)
    def warning(self,message):print(message,file=sys.stderr,flush=True)
    def error(self,message):print(message,file=sys.stderr,flush=True)


def download(spec):
    from yt_dlp import YoutubeDL
    directory=Path(spec['directory']).resolve()
    moved=[]
    last_progress=0.0
    def progress(data):
        nonlocal last_progress
        now=time.monotonic()
        if now-last_progress<.2 and data.get("status")!="finished":return
        last_progress=now
        info=data.get('info_dict') or {}
        size=data.get('total_bytes') or data.get('total_bytes_estimate') or 0
        percent=min(95,(data.get('downloaded_bytes',0)/size)*95) if size else 0
        emit(event='progress',progress=percent,title=str(info.get('title') or '')[:512])
    def moved_file(filename):moved.append(filename)
    options={
        'format':format_selector(spec['video'],spec['audio']),
        'outtmpl':str(directory/'%(title).160B [%(id)s].%(ext)s'),
        'windowsfilenames':True,'noplaylist':True,'overwrites':False,
        'writethumbnail':True,'writeinfojson':False,'cachedir':False,
        'socket_timeout':20,'retries':3,'fragment_retries':3,'concurrent_fragment_downloads':1,
        'ffmpeg_location':spec['ffmpeg'],'js_runtimes':{},
        'remote_components':set(),'quiet':True,'no_warnings':False,'logger':Log(),
        'progress_hooks':[progress], 'post_hooks':[moved_file],
        'postprocessor_hooks':[lambda _:emit(event='merging')],
        'match_filter':lambda info,**_: 'Live streams are not supported.' if info.get('is_live') else None,
    }
    with YoutubeDL(options) as ydl:
        info=ydl.extract_info(canonical_url(spec['url']),download=True)
    if not info or not moved:raise RuntimeError('No completed media output')
    media=Path(moved[-1]).resolve()
    if media.parent!=directory or not media.is_file():raise RuntimeError('Unexpected output path')
    thumbnail=next((p.name for p in directory.iterdir() if p.suffix.lower() in ('.jpg','.jpeg','.png','.webp')), '')
    emit(event='complete',path=media.name,title=str(info.get('title') or media.stem)[:512],thumbnail=thumbnail)


def main(arguments):
    if arguments: return 2
    try:
        spec=json.loads(sys.stdin.readline(16384))
        download(spec)
        return 0
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}',file=sys.stderr,flush=True)
        return 1


if __name__=='__main__':raise SystemExit(main(sys.argv[1:]))
