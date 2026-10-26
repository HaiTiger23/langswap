"""Stable text occurrences and glyph-local cleanup, with one frozen layout per label."""
import re,math
from difflib import SequenceMatcher
import numpy as np
import cv2
from PIL import Image,ImageDraw,ImageFont


def normalize(text):return re.sub(r'\W+','',text.casefold())

def median_box(samples):return np.median([s['box'] for s in samples],axis=0).tolist()

def center(box):return np.array([box[0]+box[2]/2,box[1]+box[3]/2])

def consolidate_labels(regions,include_subtitles=False):
    """OCR variants are observations of one caption, not separate overlays."""
    visible_kinds={'label','subtitle'} if include_subtitles else {'label'}
    labels=[dict(r) for r in regions if r['kind'] in visible_kinds and not r.get('mask_only') and r.get('vi') and len(r['samples'])>1]
    groups=[]
    for r in sorted(labels,key=lambda r:r['start']):
        match=None
        for g in reversed(groups):
            if r['start']>g['end']+.28:continue
            a=normalize(r['vi']);b=normalize(g['vi'])
            same=a==b or min(len(a),len(b))>=6 and (a in b or b in a)
            same=same or SequenceMatcher(None,r['text'],g['text']).ratio()>.6 and SequenceMatcher(None,a,b).ratio()>.65
            rb=median_box(r['samples']);gb=median_box(g['samples'])
            overlap=max(0,min(rb[0]+rb[2],gb[0]+gb[2])-max(rb[0],gb[0]))*max(0,min(rb[1]+rb[3],gb[1]+gb[3])-max(rb[1],gb[1]))
            fragment_overlap=(a in b or b in a) and overlap>0 and abs(center(rb)[1]-center(gb)[1])<.1
            if same and (np.linalg.norm(center(rb)-center(gb))<.15 or fragment_overlap):
                match=g;break
        if match is None:
            groups.append(r|dict(samples=list(r['samples']),members=[r['id']],canonical_samples=list(r['samples'])))
        else:
            match['members'].append(r['id']);match['start']=min(match['start'],r['start']);match['end']=max(match['end'],r['end'])
            match['samples'].extend(r['samples'])
            # Prefer the complete, stable observation rather than an entrance fragment.
            if len(r['samples'])>len(match['canonical_samples']):
                match.update(text=r['text'],vi=r['vi'],canonical_samples=list(r['samples']))
    for g in groups:
        g['start']=min(s['time'] for s in g['samples'])
        g['end']=max(s['time'] for s in g['samples'])+1/30
        samples=sorted(g['canonical_samples'],key=lambda s:s['time'])
        trim=len(samples)//8;stable=samples[trim:len(samples)-trim] if len(samples)>8 else samples
        box=median_box(stable);g['stable_box']=box;g['anchor']=center(box).tolist()
        first=np.median([center(s['box']) for s in stable[:max(2,len(stable)//4)]],axis=0)
        last=np.median([center(s['box']) for s in stable[-max(2,len(stable)//4):]],axis=0)
        # Jitter and zoom-in entrances must not move the Vietnamese caption.
        g['moving']=bool(np.linalg.norm(last-first)>.1)
        if g['moving']:
            times=np.array([s['time'] for s in stable]);points=np.array([center(s['box']) for s in stable]);smooth=[]
            for i,t in enumerate(times):smooth.append(np.median(points[np.abs(times-t)<=.22],axis=0).tolist())
            g['motion']=dict(times=times.tolist(),centers=smooth)
    # Neighboring captions in the same slot replace each other, rather than
    # stacking during OCR's entrance/exit uncertainty interval.
    for i,current in enumerate(groups):
        for later in groups[i+1:]:
            if later['start']>=current['end']:break
            if np.linalg.norm(np.array(current['anchor'])-np.array(later['anchor']))<.15:
                current['end']=max(current['start']+.07,later['start'])
                break
    return groups


def anchor_at(label,time):
    if not label['moving']:return label['anchor']
    motion=label['motion'];p=np.array(motion['centers'])
    return [float(np.interp(time,motion['times'],p[:,i])) for i in range(2)]


def glyph_mask(crop,core_height):
    """Use light fill adjacent to dark outline, not a solid OCR rectangle."""
    hsv=cv2.cvtColor(crop,cv2.COLOR_RGB2HSV);h,s,v=cv2.split(hsv)
    light=(v>165)&(s<110)
    colored=(s>100)&(v>150)
    dark=v<150
    radius=max(2,min(5,round(core_height*.07)))
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1))
    near_dark=cv2.dilate(dark.astype(np.uint8),kernel).astype(bool)
    near_bright=cv2.dilate((v>170).astype(np.uint8),kernel).astype(bool)
    near_outline=cv2.dilate((light|dark).astype(np.uint8),kernel).astype(bool)
    selected=np.zeros(dark.shape,np.uint8)
    # Recover full connected ink components after identifying their contrasting
    # edges; this includes thick pink/red letters with a white outline.
    for layer,contrast in [(light,near_dark),(colored,near_outline),(dark,near_bright)]:
        count,labels,stats,_=cv2.connectedComponentsWithStats(layer.astype(np.uint8)*255,8)
        for i in range(1,count):
            x,y,w,height,area=stats[i]
            if area<3:continue
            component=labels==i;edges=component&contrast
            edge_area=np.count_nonzero(edges)
            if edge_area<2:continue
            if height>core_height*1.7 or w>crop.shape[1]*.92 or area>crop.shape[0]*crop.shape[1]*.55:
                # White ink can connect to a white cloth, or the dark outline of
                # adjacent letters can join across the full caption. Keep their
                # contrast edges rather than dropping the entire component.
                if edge_area<crop.shape[0]*crop.shape[1]*.55:selected[edges]=255
            else:selected[component]=255
    # Plain white/gray letters on a bright background have no dark outline.
    # Top/black-hat isolates thin ink strokes from slowly varying background.
    gray=cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY)
    span=max(5,min(41,round(core_height*.45)))|1
    structure=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(span,span))
    bright=cv2.morphologyEx(gray,cv2.MORPH_TOPHAT,structure)
    dim=cv2.morphologyEx(gray,cv2.MORPH_BLACKHAT,structure)
    strokes=(((bright>18)&(v>160))|((dim>18)&(v<200))).astype(np.uint8)*255
    count,components,stats,_=cv2.connectedComponentsWithStats(strokes,8)
    for i in range(1,count):
        xx,yy,ww,hh,area=stats[i]
        if area>=3 and hh<core_height*1.7:selected[components==i]=255
    selected=cv2.dilate(selected,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+3,radius*2+3)))
    return selected


def cleanup_text(crop,core_height,subtitle=False,base=None,content_box=None):
    if content_box is None:mask=glyph_mask(crop,core_height)
    else:
        left,top,right,bottom=content_box
        mask=np.zeros(crop.shape[:2],np.uint8)
        if right>left and bottom>top:mask[top:bottom,left:right]=glyph_mask(crop[top:bottom,left:right],core_height)
    if base is None:base=crop
    if not np.any(mask):return base
    cleaned=cv2.inpaint(crop,mask,3,cv2.INPAINT_TELEA)
    if subtitle:
        # Blur restored background under the glyphs, not the white/black ink.
        cleaned=cv2.GaussianBlur(cleaned,(0,0),sigmaX=1.5)
    alpha=cv2.GaussianBlur(mask,(0,0),sigmaX=1.0).astype(np.float32)/255
    return np.clip(base*(1-alpha[:,:,None])+cleaned*alpha[:,:,None],0,255).astype(np.uint8)


def source_style(crop,core_height):
    hsv=cv2.cvtColor(crop,cv2.COLOR_RGB2HSV);h,s,v=cv2.split(hsv)
    saturated=((s>110)&(v>160)).astype(np.uint8)
    count,labels,stats,_=cv2.connectedComponentsWithStats(saturated,8)
    candidates=np.zeros(saturated.shape,bool)
    for i in range(1,count):
        x,y,w,hh,area=stats[i]
        if area>=5 and w<crop.shape[1]*.8 and hh<core_height*1.6:candidates|=labels==i
    white=(s<95)&(v>195)
    fill=(255,255,255);stroke=(18,18,18)
    if candidates.sum()>max(20,white.sum()*.3):
        bins=np.bincount((h[candidates]//12).astype(int),minlength=16);dominant=int(np.argmax(bins))
        chosen=candidates&(h//12==dominant)
        fill=tuple(int(c) for c in np.median(crop[chosen],axis=0))
        if dominant>=11:stroke=(255,255,255)
    return dict(fill=fill,stroke=stroke,stroke_width=max(1,min(4,round(core_height*.055))))


def make_label_tile(label,width,height,style):
    box=label['stable_box'];base=max(15,min(76,round(box[3]*height*1.05)))
    max_width=min(round(width*.9),max(round(box[2]*width*1.8),round(width*.32)))
    measure=ImageDraw.Draw(Image.new('RGBA',(1,1)))
    font_path='/System/Library/Fonts/Supplemental/Arial Bold.ttf'
    # Prefer one line, reducing size once if necessary; wrapping is the fallback.
    minimum=max(10,round(base*.65));single=None
    for candidate in range(base,minimum-1,-1):
        candidate_font=ImageFont.truetype(font_path,candidate)
        if measure.textlength(label['vi'],font=candidate_font)<=max_width-12:
            single=candidate;break
    if single is not None:base=single;minimum=single
    # This sizing runs once per occurrence. Never resize a label on a frame change.
    for size in range(base,minimum-1,-1):
        font=ImageFont.truetype(font_path,size);lines=[];line=''
        for word in label['vi'].split():
            test=(line+' '+word).strip()
            if line and measure.textlength(test,font=font)>max_width-12:lines.append(line);line=word
            else:line=test
        if line:lines.append(line)
        if len(lines)<=2 and all(measure.textlength(l,font=font)<=max_width-12 for l in lines):break
    text='\n'.join(lines);stroke=style['stroke_width']
    bounds=measure.multiline_textbbox((0,0),text,font=font,spacing=4,stroke_width=stroke,align='center')
    tw=math.ceil(bounds[2]-bounds[0]+12);th=math.ceil(bounds[3]-bounds[1]+10)
    tile=Image.new('RGBA',(tw,th),(0,0,0,0));draw=ImageDraw.Draw(tile)
    draw.multiline_text((6-bounds[0],5-bounds[1]),text,font=font,fill=style['fill'],stroke_width=stroke,stroke_fill=style['stroke'],spacing=4,align='center')
    return tile,dict(font_size=size,width=tw,height=th,fill=style['fill'],stroke_width=stroke,lines=lines)
