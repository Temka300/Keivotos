"""Generated local covers and panel pages; no downloaded art or real user data."""
from io import BytesIO
from pathlib import Path
import zipfile
from PIL import Image, ImageDraw, ImageFont


def font(size):
    try:return ImageFont.truetype('DejaVuSans.ttf',size)
    except OSError:return ImageFont.load_default(size=size)


def cover(title,background,accent):
    image=Image.new('RGB',(600,900),background);d=ImageDraw.Draw(image)
    d.ellipse((350,130,480,260),fill=accent)
    d.polygon([(0,570),(180,300),(410,700),(600,430),(600,900),(0,900)],fill='#222f38')
    d.polygon([(0,780),(260,460),(440,740),(600,620),(600,900),(0,900)],fill='#17232e')
    d.line([(60,900),(270,650),(310,690),(450,900)],fill=accent,width=5)
    d.text((42,45),'LOCAL STORIES',fill=accent,font=font(16))
    for i,line in enumerate(title.split(' ')):
        d.text((40,110+i*56),line.upper(),fill='#f5efe4',font=font(45))
    d.text((42,835),'01  /  A SHORT CHAPTER',fill='#dcd5cd',font=font(18))
    data=BytesIO();image.save(data,'PNG');return data.getvalue()


def page(number):
    image=Image.new('RGB',(800,1200),'#f4f1e8');d=ImageDraw.Draw(image)
    for box in [(28,28,772,475),(28,497,388,915),(410,497,772,915),(28,937,772,1140)]:
        d.rectangle(box,outline='#232323',width=4)
    for x in range(45,780,45):d.line((x,60,x-30,330),fill='#d2cec4',width=2)
    d.ellipse((550,75,660,185),outline='#454545',width=3)
    d.polygon([(32,450),(160,170),(290,450),(390,300),(490,460),(630,240),(770,440)],fill='#767771')
    d.polygon([(32,472),(230,350),(340,470),(600,380),(770,472)],fill='#303832')
    # Minimal architectural panels and speech bubbles, visibly synthetic fixture.
    for x in range(80,360,55):d.rectangle((x,635,x+32,870),outline='#555951',width=3)
    d.polygon([(45,635),(205,545),(372,635)],outline='#232323',width=4)
    d.ellipse((450,535,728,658),outline='#232323',width=2)
    d.text((478,574),'Still a long way.',fill='#333',font=font(22))
    d.ellipse((530,700,620,790),fill='#484e48');d.polygon([(535,785),(480,909),(668,909),(611,785)],fill='#484e48')
    d.line((50,1070,750,1070),fill='#777',width=2)
    d.text((70,990),'The morning train crossed the valley.',fill='#333',font=font(25))
    d.text((380,1160),str(number),fill='#444',font=font(20))
    data=BytesIO();image.save(data,'PNG');return data.getvalue()


def seed_manga(media):
    media.mkdir()
    titles=[('The Quiet Valley','#728477','#e7c49a'),('After The Rain','#596e80','#dec9af'),('Paper Moon','#665e75','#e2bec5'),('Northbound','#83786a','#efd6a2'),('Summer Letters','#6d877f','#e9d4af'),('Far From Home','#856c67','#e6bda0'),('Small Hours','#535f73','#cccaac'),('Blue Hour','#5a7984','#dfd3b7')]
    for title,bg,accent in titles:
        series=media/title;series.mkdir()
        for chapter in [1,2,10]:
            if title=='The Quiet Valley' and chapter==1:
                folder=series/'Chapter 1';folder.mkdir()
                (folder/'00-cover.png').write_bytes(cover(title,bg,accent))
                for n in range(1,13):(folder/f'{n}.png').write_bytes(page(n))
            else:
                with zipfile.ZipFile(series/f'Chapter {chapter}.cbz','w',compression=zipfile.ZIP_DEFLATED) as z:
                    z.writestr('00-cover.png',cover(title,bg,accent))
                    for n in [1,2,10]:z.writestr(f'{n}.png',page(n))
