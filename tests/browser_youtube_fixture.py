"""Test-only local download simulator: real queue/publication, no remote traffic."""
import asyncio
import logging
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
    class ExpectedFailures(logging.Filter):
        def filter(self,record):
            if record.exc_info and str(record.exc_info[1]) in ('fixture media acquisition failure','fixture annotation failure after completed publication'):
                record.msg+='; injected failure: %s';record.args=(*record.args,str(record.exc_info[1]))
                record.exc_info=None;record.exc_text=None
                record.levelno=logging.WARNING;record.levelname='WARNING'
            return True
    jobs.logger.addFilter(ExpectedFailures())
    attempts={};registration_failures=set()
    original_annotation=jobs.annotations.upsert_annotation
    def annotate(*args,**kwargs):
        relative=kwargs.get('relative_path')
        if relative in registration_failures:
            registration_failures.remove(relative)
            raise RuntimeError('fixture annotation failure after completed publication')
        return original_annotation(*args,**kwargs)
    jobs.annotations.upsert_annotation=annotate
    async def execute(job):
        _,root=jobs.destination(job['source_id'],job['root'])
        stage=jobs.child_directory(root,['.keivotos','youtube'])/job['id'];stage.mkdir()
        special=job['url'].rsplit('=',1)[-1]
        attempts[special]=attempts.get(special,0)+1
        title={'retryfailed':'Retry failure fixture','repairvideo':'Registration recovery fixture','stalefailed':'Pagination fixture retry'}.get(special,'A quiet journey through the valley')
        if special=='retryfailed' and attempts[special]<=2 or special=='stalefailed' and attempts[special]==1:
            jobs.update(job['id'],title=title)
            (stage/'unfinished.part').write_bytes(b'preserved failed attempt')
            await asyncio.sleep(.4)
            raise RuntimeError('fixture media acquisition failure')
        for progress in [10,25,45,65,90]:
            if jobs.get(job['id'])['status']=='cancelled':return
            jobs.update(job['id'],progress=progress,title=title)
            await asyncio.sleep(.7)
        shutil.copy2(media.parent/'fixture-video/sample.mp4',stage/'Valley.mp4')
        shutil.copy2(media.parent/'fixture-cover.png',stage/'cover.png')
        if special=='repairvideo':registration_failures.add(f"YouTube/{job['id']}/Valley.mp4")
        completion=asyncio.create_task(asyncio.to_thread(jobs.publish,job,stage,{'path':'Valley.mp4','thumbnail':'cover.png','title':title}))
        try:await asyncio.shield(completion)
        except asyncio.CancelledError:await completion;raise
    jobs.execute=execute
