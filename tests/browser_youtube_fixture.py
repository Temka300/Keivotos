"""Test-only local download simulator: real queue/publication, no remote traffic."""
import asyncio
from pathlib import Path
import shutil
from PIL import Image, ImageDraw


def seed(media):
    from browser_video_fixture import seed_videos
    media.mkdir()
    (media.parent/'custom-downloads').mkdir()
    seed_videos(media.parent/'fixture-video')
    image=Image.new('RGB',(640,360),'#687e8b');draw=ImageDraw.Draw(image)
    draw.ellipse((460,40,540,120),fill='#e5d1ae')
    draw.polygon([(0,340),(160,130),(330,360),(490,190),(640,350)],fill='#344851')
    image.save(media.parent/'fixture-cover.png')


def install(media):
    from modules.youtube import jobs
    from modules.youtube import router
    tools=lambda:{'ready':True,'missing':[],'ffmpeg':'fixture'}
    jobs.dependencies=tools;router.dependencies=tools
    async def execute(job):
        _,root=jobs.destination(job['source_id'],job['root'])
        stage=jobs.child_directory(root,['.keivotos','youtube'])/job['id'];stage.mkdir()
        for progress in [10,25,45,65,90]:
            if jobs.get(job['id'])['status']=='cancelled':return
            jobs.update(job['id'],progress=progress,title='A quiet journey through the valley')
            await asyncio.sleep(.7)
        shutil.copy2(media.parent/'fixture-video/sample.mp4',stage/'Valley.mp4')
        shutil.copy2(media.parent/'fixture-cover.png',stage/'cover.png')
        completion=asyncio.create_task(asyncio.to_thread(jobs.publish,job,stage,{'path':'Valley.mp4','thumbnail':'cover.png','title':'A quiet journey through the valley'}))
        try:await asyncio.shield(completion)
        except asyncio.CancelledError:await completion;raise
    jobs.execute=execute
