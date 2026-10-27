"""Local studio UI and asynchronous job API for the Vietnamese dubber."""
from __future__ import annotations
import json
import time
import uuid
import asyncio
from contextlib import suppress
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from local_dub.pipeline import ROOT, run

import fcntl
import os
import hashlib
import shutil
from contextlib import asynccontextmanager
from local_dub.job_store import JobStore
from local_dub.queue_runner import QueueRunner,recover_failed_result
from local_dub.pipeline import digest
from local_dub.timing_policy import PIPELINE_VERSION

STORE=JobStore(ROOT/'data/studio.sqlite3')
RUNNER=None
UPLOADS=ROOT/'data/studio_uploads'
UPLOADS.mkdir(parents=True,exist_ok=True)
VOICES=ROOT/'data/studio_voices'
VOICES.mkdir(parents=True,exist_ok=True)
VOICE_INDEX=VOICES/'index.json'
KINDS={'video','audio','srt','log','segments','source'}
RETENTION_SECONDS=24*60*60
RESULTS=ROOT/'data/studio_results'
CACHE_ROOT=ROOT/'data/local_dub'


def import_results():
    existing=STORE.list()
    known={j.get('result',{}).get('video') for j in existing}
    represented={digest(j['result']['segments']) for j in existing if j.get('args') and j.get('result',{}).get('segments') and Path(j['result']['segments']).is_file()}
    for manifest in sorted((ROOT/'data/local_dub').glob('*/result.json'),key=lambda p:p.stat().st_mtime):
        result=json.loads(manifest.read_text())
        legacy_id='saved-'+manifest.parent.name
        settings=json.loads((manifest.parent/'settings.json').read_text())
        if settings.get('qa_only'):continue
        if (settings.get('generation_id') and STORE.get(settings['generation_id'])) or (result.get('segments') and Path(result['segments']).is_file() and digest(result['segments']) in represented):
            if STORE.get(legacy_id):STORE.patch(legacy_id,hidden=True)
            continue
        if result.get('video') in known or not Path(result.get('video','')).is_file():continue
        result['source']=str(manifest.parent/'source.mp4')
        STORE.import_result(dict(id='saved-'+manifest.parent.name,name='Video đã lưu · '+manifest.parent.name[:6],status='done',progress=1,message='Video đã lưu từ phiên trước.',history=[],result=result,created=manifest.stat().st_mtime,finished=manifest.stat().st_mtime))


def inside(path,root):
    """Accept only a direct child of an owned storage root, never the root itself."""
    try:
        target=Path(path).resolve(strict=False);base=Path(root).resolve()
        return target.parent==base and target!=base
    except (OSError,TypeError):
        return False


def remove_owned_tree(path,root):
    if not path or not inside(path,root):
        return True
    target=Path(path)
    if not target.exists():
        return True
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return not target.exists()


def cleanup_expired_jobs(now=None):
    """Erase terminal job artefacts after 24h without touching active work or voices."""
    cutoff=(time.time() if now is None else now)-RETENTION_SECONDS
    expired=STORE.claim_expired(cutoff)
    # A cache can be reused by a still-visible task. Keep it until its last owner expires.
    retained={str(Path((job.get('result') or {}).get('cache_directory','')).resolve()) for job in STORE.list() if job.get('status')!='expired' and (job.get('result') or {}).get('cache_directory')}
    for job in expired:
        args=job.get('args') or {};result=job.get('result') or {}
        upload=Path(args['video']).parent if args.get('video') else None
        output=result.get('directory')
        cache=result.get('cache_directory')
        ok=remove_owned_tree(upload,UPLOADS) and remove_owned_tree(output,RESULTS)
        if cache and str(Path(cache).resolve()) not in retained:
            ok=remove_owned_tree(cache,CACHE_ROOT) and ok
        if ok:
            STORE.remove_expired(job['id'])


async def retention_loop():
    while True:
        await asyncio.sleep(15*60)
        cleanup_expired_jobs()
        for job in STORE.list():
            if job['status']=='error' and not (job.get('result') or {}).get('video'):
                preview=recover_failed_result(job,CACHE_ROOT,RESULTS)
                if preview:STORE.patch(job['id'],result=preview,needs_review=True)


@asynccontextmanager
async def lifespan(app):
    global RUNNER
    lease=(ROOT/'data/studio-worker.lock').open('a')
    try:
        fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lease.close();raise RuntimeError('Studio đang mở ở cửa sổ khác. Truy cập http://127.0.0.1:7860/')
    try:
        import_results()
        cleanup_expired_jobs()
        RUNNER=QueueRunner(STORE,run,ROOT/'data/studio_results');RUNNER.start()
        cleaner=asyncio.create_task(retention_loop())
        try:
            yield
        finally:
            cleaner.cancel()
            with suppress(asyncio.CancelledError):
                await cleaner
    finally:
        if RUNNER:RUNNER.stop()
        fcntl.flock(lease,fcntl.LOCK_UN);lease.close()


app=FastAPI(title='Lồng · Local dubbing studio',docs_url=None,redoc_url=None,lifespan=lifespan)
app.mount('/assets',StaticFiles(directory=ROOT/'studio'),name='assets')


def public(job,position=None):
    result=job.get('result') or {}
    files={kind:f'/api/jobs/{job["id"]}/files/{kind}' for kind in KINDS if result.get(kind)}
    if job.get('args',{}).get('video'):files['source']=f'/api/jobs/{job["id"]}/files/source'
    return {k:v for k,v in job.items() if k not in ('result','args','fingerprint')} | {'files':files,'queue_position':position}


def snapshot():
    jobs=[j for j in STORE.list() if not j.get('hidden')]
    queued=sorted((j for j in jobs if j['status']=='queued'),key=lambda j:j.get('queued_at',j['created']))
    positions={j['id']:i+1 for i,j in enumerate(queued)}
    counts={s:sum(j['status']==s for j in jobs) for s in ['queued','running','done','error','cancelled']}
    return dict(jobs=[public(j,positions.get(j['id'])) for j in jobs],counts=counts,paused=STORE.paused())


def fingerprint(args):
    value=dict(video=digest(args['video']),reference=digest(args['reference']) if args.get('reference') else '',reference_text=(args.get('reference_text') or '').strip(),duck_db=float(args['duck_db']),steps=int(args['steps']),pipeline=PIPELINE_VERSION,glossary=digest(ROOT/'local_dub/glossary.json'),backend='agy',model=os.getenv('DUB_AGY_MODEL','gemini-3.8-flash-medium'),text_mode=args.get('text_mode','off'),reuse_dub_directory=args.get('reuse_dub_directory',''))
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def voices():
    """Read the small local voice library without ever exposing disk paths."""
    try:
        data=json.loads(VOICE_INDEX.read_text(encoding='utf-8'))
        return data if isinstance(data,list) else []
    except (OSError,json.JSONDecodeError):
        return []


def write_voices(items):
    temporary=VOICE_INDEX.with_suffix('.partial')
    temporary.write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(VOICE_INDEX)


def public_voice(item):
    return {key:item[key] for key in ('id','name','reference_text','created','size')}


def saved_voice(voice_id):
    if not voice_id or len(voice_id)>64:
        return None
    item=next((entry for entry in voices() if entry.get('id')==voice_id),None)
    if not item:
        return None
    path=(VOICES/voice_id/item.get('file','')).resolve()
    if not path.is_relative_to(VOICES.resolve()) or not path.is_file():
        return None
    return item,path


@app.get('/')
def home():
    return FileResponse(ROOT/'studio/index.html')


@app.get('/manifest.webmanifest')
def manifest():
    return FileResponse(ROOT/'studio/manifest.webmanifest',media_type='application/manifest+json')


@app.get('/sw.js')
def service_worker():
    return FileResponse(ROOT/'studio/sw.js',media_type='application/javascript')


async def save_upload(upload,folder,name,limit):
    dest=folder/(name+Path(upload.filename or '').suffix.lower())
    size=0
    try:
        with dest.open('wb') as f:
            while chunk:=await upload.read(1024*1024):
                size+=len(chunk)
                if size>limit:
                    raise HTTPException(413,'File quá lớn. Vui lòng chọn video dưới 256 MB hoặc mẫu giọng dưới 20 MB.')
                f.write(chunk)
        if not size:
            raise HTTPException(400,'File tải lên đang trống.')
        return str(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


@app.post('/api/jobs')
async def create_job(video:UploadFile=File(...),reference:Optional[UploadFile]=File(None),reference_text:Optional[str]=Form(''),voice_id:Optional[str]=Form(None),duck_db:float=Form(9),steps:int=Form(16),submission_id:Optional[str]=Form(None),text_mode:str=Form('off')):
    if text_mode not in ('off','subtitles','all','all_subtitles'):raise HTTPException(400,'Chế độ xử lý chữ không hợp lệ.')
    if submission_id and len(submission_id)>128:raise HTTPException(400,'Mã lượt gửi không hợp lệ.')
    if not 0<=duck_db<=18 or steps not in (16,32):
        raise HTTPException(400,'Cấu hình giọng đọc hoặc âm lượng không hợp lệ.')
    if reference and voice_id:
        raise HTTPException(400,'Chọn giọng đã lưu hoặc tải mẫu giọng mới, không dùng cả hai.')
    if reference and not (reference_text or '').strip():
        raise HTTPException(400,'Nhập lời nói trong mẫu giọng, hoặc bỏ mẫu để dùng giọng tự động.')
    voice=saved_voice(voice_id) if voice_id else None
    if voice_id and not voice:
        raise HTTPException(404,'Không còn tìm thấy giọng đã lưu. Hãy chọn lại hoặc thêm mẫu mới.')
    folder=UPLOADS/uuid.uuid4().hex;folder.mkdir()
    name=video.filename or 'Video mới'
    source=await save_upload(video,folder,'video',256*1024*1024)
    ref=await save_upload(reference,folder,'reference',20*1024*1024) if reference else (str(voice[1]) if voice else None)
    ref_text=(voice[0]['reference_text'] if voice else reference_text) or ''
    args=dict(video=source,reference=ref,reference_text=ref_text,duck_db=duck_db,steps=steps,text_mode=text_mode,voice_id=voice[0]['id'] if voice else '')
    job,reused=STORE.enqueue(name,args,fingerprint(args),submission_id)
    if reused:shutil.rmtree(folder)
    RUNNER.notify()
    return public(job) | {'reused':reused}


@app.get('/api/voices')
def list_voices():
    return {'voices':[public_voice(item) for item in sorted(voices(),key=lambda item:item.get('created',0),reverse=True)]}


@app.post('/api/voices')
async def create_voice(reference:UploadFile=File(...),reference_text:Optional[str]=Form(''),name:Optional[str]=Form('')):
    text=(reference_text or '').strip()
    label=' '.join((name or '').split())[:60]
    if not text:
        raise HTTPException(400,'Nhập đúng lời nói trong mẫu giọng trước khi lưu.')
    if not label:
        raise HTTPException(400,'Đặt tên cho giọng để dễ chọn ở lần sau.')
    voice_id=uuid.uuid4().hex
    folder=VOICES/voice_id
    folder.mkdir()
    try:
        path=Path(await save_upload(reference,folder,'reference',20*1024*1024))
        item=dict(id=voice_id,name=label,reference_text=text,created=time.time(),size=path.stat().st_size,file=path.name)
        all_voices=voices();all_voices.append(item);write_voices(all_voices)
        return public_voice(item)
    except Exception:
        shutil.rmtree(folder,ignore_errors=True)
        raise


@app.delete('/api/voices/{voice_id}')
def delete_voice(voice_id:str):
    found=saved_voice(voice_id)
    if not found:
        raise HTTPException(404,'Không tìm thấy giọng đã lưu.')
    write_voices([item for item in voices() if item.get('id')!=voice_id])
    shutil.rmtree(VOICES/voice_id,ignore_errors=True)
    return {'ok':True}


@app.get('/api/jobs')
def all_jobs():return snapshot()


@app.post('/api/queue/pause')
def pause_queue(paused:bool=Form(...)):
    STORE.pause(paused);RUNNER.notify();return snapshot()


@app.post('/api/jobs/{job_id}/cancel')
def cancel_job(job_id:str):
    job=STORE.cancel(job_id)
    if not job:raise HTTPException(404,'Không tìm thấy tác vụ.')
    RUNNER.cancel(job_id);return public(job)


@app.post('/api/jobs/{job_id}/retry')
def retry_job(job_id:str):
    job=STORE.get(job_id)
    if not job:raise HTTPException(404,'Không tìm thấy tác vụ.')
    if not job.get('args'):raise HTTPException(400,'Hãy tải lại video này để tạo tác vụ mới.')
    job=STORE.retry(job_id);RUNNER.notify();return public(job)


@app.post('/api/jobs/{job_id}/rerun')
def rerun_job(job_id:str):
    old=STORE.get(job_id)
    if not old:raise HTTPException(404,'Không tìm thấy tác vụ.')
    args=dict(old.get('args') or {})
    args.pop('generation_id',None)
    if not args:
        source=old.get('result',{}).get('source')
        if not source or not Path(source).is_file():raise HTTPException(400,'Không còn video gốc; hãy tải video lên lại.')
        args=dict(video=source,reference=None,reference_text='',duck_db=9,steps=16)
    job,_=STORE.enqueue(old['name'],args,fingerprint(args))
    RUNNER.notify();return public(job)


@app.post('/api/jobs/{job_id}/screen')
def screen_job(job_id:str,text_mode:str=Form('all')):
    if text_mode not in ('subtitles','all','all_subtitles'):raise HTTPException(400,'Chọn làm mờ phụ đề hoặc Việt hóa chữ.')
    old=STORE.get(job_id)
    if not old or old['status']!='done':raise HTTPException(400,'Cần một video đã lồng tiếng xong.')
    result=old.get('result') or {}
    source=old.get('args',{}).get('video') or result.get('source')
    folder=result.get('directory')
    if not folder or not source or not Path(source).is_file() or not (Path(folder)/'mixed_vi.wav').is_file():raise HTTPException(400,'Không còn đủ video gốc và âm thanh đã lưu.')
    args=dict(video=source,reference=None,reference_text='',duck_db=9,steps=16,text_mode=text_mode,reuse_dub_directory=folder)
    job,_=STORE.enqueue(old['name']+' · Việt hóa chữ',args,fingerprint(args))
    RUNNER.notify();return public(job)


@app.get('/api/jobs/{job_id}')
def get_job(job_id:str):
    job=STORE.get(job_id)
    if not job:raise HTTPException(404,'Không tìm thấy tác vụ.')
    return public(job)


@app.get('/api/library/latest')
def latest():
    job=next((j for j in STORE.list() if j['status']=='done' and not j.get('hidden')),None)
    if not job:raise HTTPException(404,'Chưa có video hoàn tất.')
    return public(job)


@app.get('/api/jobs/{job_id}/files/{kind}')
def get_file(job_id:str,kind:str):
    job=STORE.get(job_id) or {}
    result=dict(job.get('result') or {})
    if job.get('args',{}).get('video'):result['source']=job['args']['video']
    if kind not in KINDS or not result.get(kind): raise HTTPException(404,'File chưa sẵn sàng.')
    path=Path(result[kind]).resolve()
    if not path.is_relative_to(ROOT/'data') or not path.is_file(): raise HTTPException(404,'Không tìm thấy file.')
    media={'video':'video/mp4','source':'video/mp4','audio':'audio/wav','srt':'text/plain','log':'text/plain','segments':'application/json'}[kind]
    inline=kind in ('video','source','audio')
    return FileResponse(path,media_type=media,filename=path.name,content_disposition_type='inline' if inline else 'attachment')


if __name__=='__main__':
    host=os.getenv('STUDIO_HOST','0.0.0.0')
    port=int(os.getenv('STUDIO_PORT','7860'))
    uvicorn.run(app,host=host,port=port,log_level='info')
