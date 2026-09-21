"""Tiny synthetic codec fixtures, generated locally with the existing FFmpeg."""
from pathlib import Path
import subprocess
import imageio_ffmpeg


def seed_videos(media: Path):
    media.mkdir()
    for name, codec in [('sample.mp4', 'libx264'), ('sample.webm', 'libvpx')]:
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=12', '-t', '4',
                        '-c:v', codec, '-pix_fmt', 'yuv420p', '-an', str(media / name)], check=True)
    (media / 'sample.m4v').write_bytes((media / 'sample.mp4').read_bytes())
    (media / 'unsupported.avi').write_bytes(b'unsupported fixture')
    (media / 'broken.mp4').write_bytes(b'invalid media fixture')
    (media / 'notes.txt').write_text('not a video')
