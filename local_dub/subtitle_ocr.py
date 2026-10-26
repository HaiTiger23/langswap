"""Read burned-in Chinese subtitles locally; only extracted text goes to the LLM."""
from pathlib import Path
import json
import re
from difflib import SequenceMatcher


def normalize(text):return re.sub(r'[\s，。！？、,.!?：:「」“”]','',text)


def group_captions(frames,interval=.5,total=0):
    groups=[]
    for idx,frame in enumerate(frames):
        candidates=[l for l in frame.get('lines',[]) if l.get('confidence',0)>=.55 and len(normalize(l.get('text','')))>=2]
        if not candidates:continue
        # The longest centered Chinese line is usually the subtitle, not a corner watermark.
        line=max(candidates,key=lambda l:len(normalize(l['text']))*l['confidence'])
        text=normalize(line['text']);t=idx*interval
        if groups and t-groups[-1]['last']<=interval*2.1 and SequenceMatcher(None,text,normalize(groups[-1]['zh'])).ratio()>=.88:
            groups[-1]['last']=t
            if len(text)>len(groups[-1]['zh']):groups[-1]['zh']=text
        else:groups.append(dict(zh=text,first=t,last=t))
    result=[]
    for i,g in enumerate(groups):
        start=max(0,g['first']-interval/2)
        end=min(total,g['last']+interval*1.5)
        if i+1<len(groups):end=min(end,(g['last']+groups[i+1]['first'])/2)
        if end>start:result.append(dict(start=round(start,3),end=round(end,3),zh=g['zh'],source='ocr'))
    return merge_fragments(result)


def merge_fragments(segments,max_seconds=6):
    """Join adjacent caption fragments before translating or synthesizing speech."""
    merged=[]
    for s in segments:
        if merged and s['start']-merged[-1]['end']<=.35 and s['end']-merged[-1]['start']<=max_seconds:
            merged[-1]['zh']+='，'+s['zh']
            merged[-1]['end']=s['end']
        else:merged.append(dict(s))
    return merged


def read_subtitles(video,work,total,command,report):
    root=Path(work)/'subtitle_ocr';root.mkdir(exist_ok=True)
    dest=root/'captions.json'
    if dest.exists():return json.loads(dest.read_text())
    tool=Path(__file__).parent/'bin/ocr_subtitles'
    if not tool.exists():
        try:command(['swiftc','-O',Path(__file__).parent/'ocr_subtitles.swift','-o',tool,'-framework','Vision','-framework','AppKit'],root/'ocr.log')
        except (OSError,RuntimeError):return []
    frames=root/'frames';frames.mkdir(exist_ok=True)
    report(.23,'3/6 — Đọc phụ đề Trung có sẵn trên hình bằng OCR tại máy')
    command([__import__('local_dub.pipeline',fromlist=['FFMPEG']).FFMPEG,'-y','-i',video,'-vf','fps=2,scale=960:-1','-q:v','2',frames/'%05d.jpg'],root/'ocr.log')
    paths=sorted(frames.glob('*.jpg'))
    # Batches avoid system argument limits and make cancellation observable.
    raw=[]
    import subprocess,os
    from local_dub.pipeline import check_cancel
    for offset in range(0,len(paths),36):
        check_cancel()
        p=subprocess.run([str(tool),*[str(p) for p in paths[offset:offset+36]]],capture_output=True,text=True,timeout=120)
        if p.returncode:return []
        raw.extend(json.loads(p.stdout))
    groups=group_captions(raw,total=total)
    (root/'raw.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2))
    dest.write_text(json.dumps(groups,ensure_ascii=False,indent=2))
    return groups


def credible_captions(captions,total):
    if len(captions)<3:return False
    chars=sum(len(normalize(s['zh'])) for s in captions)
    covered=sum(s['end']-s['start'] for s in captions)
    return chars/max(total,.1)>=2 and covered/max(total,.1)>=.4
