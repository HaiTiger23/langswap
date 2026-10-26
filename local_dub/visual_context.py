"""Deterministic 12-frame 4-column × 3-row contact sheet, with time labels."""
from pathlib import Path
import json
from PIL import Image,ImageDraw,ImageFont


def make_storyboard(video,work,total,command):
    from local_dub.pipeline import FFMPEG
    work=Path(work);out=work/'storyboard_4x3.jpg'
    if out.exists() and (work/'storyboard.json').exists():return out
    folder=work/'storyboard_frames';folder.mkdir(exist_ok=True)
    frames=[]
    for i in range(12):
        time=total*(i+.5)/12
        path=folder/f'{i:02d}.jpg'
        command([FFMPEG,'-y','-ss',str(time),'-i',video,'-frames:v','1','-vf','scale=320:-1','-q:v','2',path],work/'process.log')
        frames.append((time,path))
    width=320;height=max(Image.open(p).height for _,p in frames)
    sheet=Image.new('RGB',(width*4,(height+28)*3),'#20251e');draw=ImageDraw.Draw(sheet)
    try:font=ImageFont.truetype('/System/Library/Fonts/Menlo.ttc',14)
    except OSError:font=ImageFont.load_default()
    for i,(time,path) in enumerate(frames):
        x=i%4*width;y=i//4*(height+28)
        with Image.open(path) as frame:sheet.paste(frame,(x,y+28))
        draw.text((x+9,y+6),f'{i+1:02d}   {time:05.2f}s',font=font,fill='#e4e8dc')
    temp=out.with_suffix('.partial.jpg');sheet.save(temp,quality=90);temp.replace(out)
    (work/'storyboard.json').write_text(json.dumps(dict(columns=4,rows=3,frames=[dict(index=i+1,time=round(t,3)) for i,(t,_) in enumerate(frames)]),indent=2))
    return out
