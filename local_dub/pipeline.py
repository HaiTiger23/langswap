"""Chinese -> Vietnamese short-video dubbing on macOS, with resumable stages."""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import signal
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from local_dub.translation_utils import retime_word_budget
from local_dub.timing_policy import MAX_SPEED,PREFERRED_SPEED,PIPELINE_VERSION
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
OMNI_ROOT = Path(os.getenv('OMNIVOICE_ROOT', str(ROOT.parent / 'OmniVoice')))
BUNDLED = ROOT.parent / 'voice-text-studio/resources/ffmpeg/darwin-arm64'
FFMPEG = os.getenv('DUB_FFMPEG', str(BUNDLED / 'ffmpeg') if (BUNDLED / 'ffmpeg').exists() else shutil.which('ffmpeg') or 'ffmpeg')
FFPROBE = os.getenv('DUB_FFPROBE', str(BUNDLED / 'ffprobe') if (BUNDLED / 'ffprobe').exists() else shutil.which('ffprobe') or 'ffprobe')


_CANCEL = threading.local()


def check_cancel():
    event=getattr(_CANCEL,'event',None)
    if event and event.is_set():
        raise InterruptedError('Đã dừng xử lý; các bước hoàn tất được giữ lại.')


def terminate_process(p):
    if p.poll() is not None: return
    try:os.killpg(p.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try: p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=5)


def command(args, log, timeout=1200):
    check_cancel()
    env = os.environ.copy()
    env['PATH'] = str(Path(FFMPEG).parent) + os.pathsep + env.get('PATH', '')
    with open(log, 'a') as f:
        p=subprocess.Popen([str(x) for x in args],stdout=f,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        started=time.monotonic()
        try:
            while p.poll() is None:
                check_cancel()
                if time.monotonic()-started>timeout:raise TimeoutError('Quá thời gian xử lý âm thanh.')
                try:p.wait(timeout=.2)
                except subprocess.TimeoutExpired:pass
            if p.returncode:
                raise RuntimeError(f'Lệnh xử lý thất bại ({p.returncode}):\n'+Path(log).read_text(errors='replace')[-2500:])
        finally:terminate_process(p)


def stream_command(args,log,env=None,cwd=None,timeout=1800):
    check_cancel()
    log_start=Path(log).stat().st_size if Path(log).exists() else 0
    with Path(log).open('a') as f:
        p=subprocess.Popen([str(x) for x in args],cwd=cwd,stdout=subprocess.PIPE,stderr=f,text=True,env=env,start_new_session=True)
        lines=queue.Queue()
        def read():
            try:
                for line in p.stdout:lines.put(line)
            finally:lines.put(None)
        reader=threading.Thread(target=read,daemon=True);reader.start()
        started=time.monotonic()
        try:
            while True:
                check_cancel()
                if time.monotonic()-started>timeout:raise TimeoutError('Quá thời gian chạy model.')
                try:line=lines.get(timeout=.2)
                except queue.Empty:continue
                if line is None:break
                f.write(line);f.flush()
                yield line
            if p.wait():
                f.flush()
                with Path(log).open('rb') as errors:
                    errors.seek(log_start)
                    detail=errors.read().decode('utf-8',errors='replace')
                marker=detail.rfind('RuntimeError: ')
                if marker>=0:detail=detail[marker+len('RuntimeError: '):]
                raise RuntimeError('Model xử lý thất bại:\n'+detail[-2500:].strip())
        finally:
            terminate_process(p)
            reader.join(timeout=2)
            p.stdout.close()


def save_json(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    tmp.replace(path)


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def duration(path):
    p = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    return float(json.loads(p.stdout)['format']['duration'])


def tempo_filters(rate):
    filters = []
    while rate > 2:
        filters.append('atempo=2')
        rate /= 2
    while rate < .5:
        filters.append('atempo=0.5')
        rate *= 2
    return ','.join(filters + [f'atempo={rate:.8f}'])


def timed_segments(segments):
    """Split dense continuous Mandarin speech on punctuation or ~5-second windows."""
    result = []
    current = []
    def flush():
        if current:
            result.append(dict(start=current[0].start, end=current[-1].end,
                               zh=''.join(x.word for x in current).strip()))
            current.clear()
    for seg in segments:
        words = seg.words or []
        if not words:
            flush()
            if seg.text.strip():
                result.append(dict(start=seg.start,end=seg.end,zh=seg.text.strip()))
            continue
        for w in words:
            if current and w.start-current[-1].end > .6:
                flush()
            current.append(w)
            if w.end-current[0].start >= 5 or re.search(r'[。！？!?；;]',w.word):
                flush()
    flush()
    return [s for s in result if s['end'] > s['start'] and s['zh']]


def srt_timestamp(t):
    ms = max(0, round(t * 1000))
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def write_srt(path, segments, key):
    path.write_text('\n\n'.join(f"{i+1}\n{srt_timestamp(s['start'])} --> {srt_timestamp(s['end'])}\n{s[key]}" for i,s in enumerate(segments))+'\n', encoding='utf-8')


def run(*args,cancel_event=None,**kwargs):
    _CANCEL.event=cancel_event
    try:
        check_cancel()
        return _run(*args,**kwargs)
    finally:
        _CANCEL.event=None


def _run(video, reference=None, reference_text='', voice_id='', duck_db=9, steps=16, emit=lambda p,m: None, generation_id=None,text_mode='off',reuse_dub_directory=None):
    from local_dub.screen_text import MODES
    if text_mode not in MODES:raise ValueError('Chế độ xử lý chữ không hợp lệ.')
    reference_text = (reference_text or '').strip()
    video = Path(video).resolve()
    if not video.is_file():
        raise ValueError('Hãy chọn file video.')
    omni_python = OMNI_ROOT / '.venv/bin/python'
    if not omni_python.is_file():
        raise RuntimeError(f'Không tìm thấy môi trường OmniVoice tại {OMNI_ROOT}. Đặt OMNIVOICE_ROOT để đổi đường dẫn.')
    if reference and not reference_text:
        raise ValueError('Hãy nhập đúng lời của mẫu giọng để clone ổn định.')
    total_duration = duration(video)
    if not 0 < total_duration <= 300:
        raise ValueError('Bản này nhận video dài tối đa 5 phút.')
    settings = dict(video=digest(video), reference=digest(reference) if reference else '', reference_text=reference_text.strip(), voice_id=str(voice_id or ''), steps=int(steps), version=PIPELINE_VERSION, analysis_version=3, glossary=digest(ROOT/'local_dub/glossary.json'), translation_backend='agy',translator=os.getenv('DUB_AGY_MODEL','gemini-3.8-flash-medium'),text_mode=text_mode,reuse_dub_directory=str(reuse_dub_directory or ''))
    if generation_id:settings['generation_id']=str(generation_id)
    job_id = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]
    work = ROOT / 'data/local_dub' / job_id
    work.mkdir(parents=True, exist_ok=True)
    log = work / 'process.log'
    log.touch(exist_ok=True)
    started = time.monotonic()
    def report(p, text):
        check_cancel()
        msg = f'[{time.monotonic()-started:.0f}s] {text}'
        with log.open('a') as f:
            f.write(msg+'\n')
        save_json(work / 'status.json', dict(progress=p, message=msg, updated=time.time()))
        emit(p, msg)
    save_json(work / 'settings.json', settings)
    if reuse_dub_directory:
        previous=Path(reuse_dub_directory).resolve()
        if not previous.is_relative_to(ROOT/'data'):raise ValueError('Không tìm thấy kết quả lồng tiếng đã lưu.')
        if text_mode=='off':raise ValueError('Hãy chọn chế độ xử lý chữ.')
        from local_dub.screen_text import process
        segments=json.loads((previous/'segments.json').read_text())
        outputs=dict(audio=str(previous/'mixed_vi.wav'),srt=str(previous/'vietnamese.srt'),segments=str(previous/'segments.json'),log=str(log),directory=str(work))
        result=process(video,Path(outputs['audio']),segments,work/'screen_text',total_duration,text_mode,command,report)
        outputs['video']=str(result)
        save_json(work/'result.json',outputs)
        report(1,'Hoàn tất — đã xử lý chữ trên hình, giữ nguyên bản lồng tiếng đã lưu.')
        return outputs
    if not (work/'transcript.json').exists():
        for old in (ROOT/'data/local_dub').glob('*/settings.json'):
            try:
                previous=json.loads(old.read_text())
                if old.parent==work or previous.get('video')!=settings['video'] or previous.get('analysis_version')!=3:
                    continue
                if not (old.parent/'transcript.json').exists():
                    continue
                if not all((old.parent/'stems'/f'{n}.wav').exists() for n in ['vocals','bass','drums','other']):
                    continue
                shutil.copy2(old.parent/'transcript.json',work/'transcript.json')
                shutil.copytree(old.parent/'stems',work/'stems',dirs_exist_ok=True)
                if (old.parent/'original.wav').exists():
                    shutil.copy2(old.parent/'original.wav',work/'original.wav')
                break
            except (OSError,ValueError):
                continue
    source = work / 'source.mp4'
    if not source.exists():
        shutil.copy2(video, source)
    try:
        report(.02, '1/6 — Tách âm thanh từ video')
        audio = work / 'original.wav'
        if not audio.exists():
            command([FFMPEG,'-y','-i',source,'-vn','-ac','2','-ar','44100',audio], log)
        report(.08, '2/6 — Demucs tách giọng Trung khỏi nhạc nền; lần đầu có thể cần tải model')
        stems = work / 'stems'
        names = ['vocals','bass','drums','other']
        if not all((stems / f'{n}.wav').exists() for n in names):
            # Keep Demucs separate so its memory is freed before ASR and TTS.
            env = os.environ.copy()
            env['TORCH_HOME'] = str(ROOT / 'models_weights')
            command([sys.executable, '-m', 'local_dub.separate_worker', audio, stems], log)
        vocals = stems / 'vocals.wav'
        transcript = work / 'transcript.json'
        report(.22, '3/6 — Đọc lời Trung gốc; ưu tiên phụ đề trên video, dùng Qwen3-ASR khi cần')
        if transcript.exists():
            segments = json.loads(transcript.read_text())
        else:
            from local_dub.subtitle_ocr import read_subtitles,credible_captions
            captions=read_subtitles(source,work,total_duration,command,report)
            if credible_captions(captions,total_duration):
                segments=captions
                save_json(transcript,segments)
                save_json(work/'analysis_source.json',dict(source='burned_in_chinese_subtitles',count=len(segments),local_ocr=True))
                report(.37,f'3/6 — Đọc được {len(segments)} câu từ phụ đề Trung gốc trên video')
            else:
                command([FFMPEG,'-y','-i',audio,'-ac','1','-ar','16000',work/'asr_original_16k.wav'],log)
                for line in stream_command([sys.executable,'-u',ROOT/'local_dub/asr_worker.py',work],log):
                    report(.3,'3/6 — '+line.strip())
                segments=json.loads(transcript.read_text())
                save_json(work/'analysis_source.json',dict(source='qwen_asr_original_audio',count=len(segments),local_ocr=False))
        report(.40, '4/6 — agy dịch toàn bộ phụ đề Trung → Việt trong một lượt')
        translated = work / 'segments.json'
        if not translated.exists():
            from local_dub.visual_context import make_storyboard
            report(.41,'4/6 — Ghép 12 frame (4×3) làm ngữ cảnh cho agy')
            make_storyboard(source,work,total_duration,command)
            for line in stream_command([sys.executable,'-u',ROOT/'local_dub/translate_worker.py',work],log):
                report(.43,'4/6 — '+line.strip())
            if not (work/'sentence_anchors.json').exists():
                report(.45,'4/6 — Đã dịch toàn bộ; căn từng câu Trung theo âm thanh gốc')
                command([FFMPEG,'-y','-i',audio,'-ac','1','-ar','16000',work/'alignment_16k.wav'],log)
                for line in stream_command([sys.executable,'-u',ROOT/'local_dub/alignment_worker.py',work],log):
                    report(.46,'4/6 — '+line.strip())
            report(.48,'4/6 — Chia bản dịch Việt đã chốt vào từng mốc câu gốc, giữ đủ từ')
            for line in stream_command([sys.executable,'-u',ROOT/'local_dub/translate_worker.py',work,'--partition'],log):
                report(.49,'4/6 — '+line.strip())
        segments = json.loads(translated.read_text())
        write_srt(work/'chinese.srt',segments,'zh')
        from local_dub.pacing import plan_pacing
        if not (work/'partitioned_segments.json').exists():save_json(work/'partitioned_segments.json',segments)
        for pace_round in range(3):
            pacing=plan_pacing(segments,total_duration)
            save_json(work/'pacing_plan.json',pacing)
            requests=pacing['rewrite_requests']
            if not requests:
                for segment,plan in zip(segments,pacing['plans']):segment.update(plan)
                save_json(translated,segments)
                report(.51,f"5/6 — Nhịp đọc chung {pacing['target_sps']:.1f} âm tiết/giây; tạo giọng theo thời lượng đã lên kế hoạch")
                break
            if pace_round==2:raise RuntimeError('Một số câu vẫn quá dày so với nhịp đọc chung; chưa xuất video để tránh giọng lúc nhanh lúc chậm.')
            report(.50,f"4/6 — Điều chỉnh {len(requests)} câu quá dày theo nhịp đọc chung {pacing['target_sps']:.1f} âm tiết/giây, giữ đầy đủ hành động và ý chính")
            save_json(work/'retime_request.json',requests)
            for line in stream_command([sys.executable,'-u',ROOT/'local_dub/translate_worker.py',work,'--retime'],log):
                report(.50,'4/6 — '+line.strip())
            segments=json.loads(translated.read_text())
            for idx in requests:(work/'voice'/f'{int(idx):04d}.wav').unlink(missing_ok=True)
        # OCR only consumes the original video. Start it while OmniVoice is working
        # so the final mux stage does not sit idle scanning every frame first.
        screen_executor=None
        screen_scan=None
        parallel_progress={'value':.52}
        if text_mode!='off':
            from local_dub.screen_text import detect
            screen_work=work/'screen_text'
            inherited_cancel=getattr(_CANCEL,'event',None)
            def scan_screen_in_parallel():
                # Cancellation state is thread-local in this pipeline; explicitly
                # carry it to the OCR worker so cancelling a job stops both tasks.
                _CANCEL.event=inherited_cancel
                try:
                    # Keep the visible overall progress owned by OmniVoice; OCR
                    # reports its live frame count without making the bar jump back.
                    return detect(work/'source.mp4',screen_work,total_duration,command,lambda _p,message:report(parallel_progress['value'],message.replace('6/6 — ','5/6 — Quét chữ song song · ')))
                finally:
                    _CANCEL.event=None
            report(.51,'5/6 — Tạo giọng Việt và quét chữ Trung trên hình song song')
            screen_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='screen-ocr')
            screen_scan=screen_executor.submit(scan_screen_in_parallel)
        for timing_round in range(3):
            report(.52,'5/6 — OmniVoice tạo giọng Việt trực tiếp trên Mac')
            voice_dir = work / 'voice'
            voice_dir.mkdir(exist_ok=True)
            if not all((voice_dir/f'{i:04d}.wav').exists() for i in range(len(segments))):
                model_id = os.getenv('DUB_OMNIVOICE_MODEL','k2-fsa/OmniVoice')
                # Prefer existing cached weights and avoid duplicate downloads.
                snapshots = Path.home()/'.cache/huggingface/hub/models--k2-fsa--OmniVoice/snapshots'
                if model_id == 'k2-fsa/OmniVoice' and snapshots.exists():
                    candidates = [p for p in snapshots.iterdir() if (p/'config.json').exists()]
                    if candidates:
                        model_id = str(sorted(candidates,key=lambda p:p.stat().st_mtime)[-1])
                job = work/'voice_job.json'
                save_json(job,dict(directory=str(work),segments=segments,model=model_id,reference=str(Path(reference).resolve()) if reference else None,reference_text=reference_text,steps=int(steps)))
                env = os.environ.copy()
                env['PYTORCH_ENABLE_MPS_FALLBACK']='1'
                env.pop('TRANSFORMERS_CACHE',None)
                env.pop('HUGGINGFACE_HUB_CACHE',None)
                for line in stream_command([omni_python,'-u',ROOT/'local_dub/voice_worker.py',job],log,env=env,cwd=str(OMNI_ROOT)):
                    try:event=json.loads(line)
                    except ValueError:continue
                    if event.get('status')=='segment':
                        parallel_progress['value']=.52+.27*event['done']/event['total']
                        report(parallel_progress['value'],f"5/6 — Đã tạo giọng Việt {event['done']}/{event['total']} câu")
                    elif event.get('message'):
                        report(.52,event['message'])

            too_long={}
            for idx,segment in enumerate(segments):
                info=sf.info(voice_dir/f'{idx:04d}.wav')
                window=max(.1,min(segment.get('fit_end',segment['end']),segments[idx+1]['start'] if idx+1<len(segments) else total_duration,total_duration)-segment['start'])
                planned=min(window,float(segment.get('target_duration',window)))
                actual=info.frames/info.samplerate
                # Validate against the same cadence target used by the mixer,
                # rather than the wider source window. This guarantees a full
                # natural utterance is rewritten before it would need >3x tempo.
                budget=retime_word_budget(segment['vi'],planned,actual)
                if budget is not None:
                    too_long[str(idx)]=dict(budget=budget,actual=round(actual,3))
            if not too_long:break
            if timing_round==2:
                numbers=', '.join(str(int(i)+1) for i in too_long)
                raise RuntimeError(f'Câu {numbers} vẫn cần tăng tốc quá {MAX_SPEED:g}× sau hai lần viết gọn; chưa xuất video để tránh vượt tốc độ cho phép hoặc cắt mất lời.')
            report(.55,f'5/6 — {len(too_long)} câu vượt thời gian đọc; agy đang viết gọn lại (lần {timing_round+1}/2)')
            save_json(work/'retime_request.json',too_long)
            for line in stream_command([sys.executable,'-u',ROOT/'local_dub/translate_worker.py',work,'--retime'],log):
                report(.55,'5/6 — '+line.strip())
            segments=json.loads(translated.read_text())
            refreshed=plan_pacing(segments,total_duration)
            if refreshed['rewrite_requests']:raise RuntimeError('Lời sau điều chỉnh chưa đạt nhịp đọc chung; chưa xuất để tránh tốc độ không đều.')
            save_json(work/'pacing_plan.json',refreshed)
            for segment,plan in zip(segments,refreshed['plans']):segment.update(plan)
            save_json(translated,segments)
            for idx in too_long:(voice_dir/f'{int(idx):04d}.wav').unlink(missing_ok=True)
        write_srt(work/'vietnamese.srt',segments,'vi')
        report(.81,'6/6 — Căn thời gian từng câu, ducking nhạc nền và xuất MP4')
        result = mix_and_mux(work,segments,total_duration,float(duck_db),log,report,mux_video=text_mode=='off')
        if text_mode!='off':
            from local_dub.screen_text import process
            report(.86,'6/6 — Dùng kết quả quét chữ đã chạy song song; phân loại và dựng bản xuất')
            # Surface an OCR error before classification. process() reads the same
            # cached tracks, so this does not scan the original video a second time.
            screen_scan.result()
            screen_executor.shutdown(wait=True)
            result=process(work/'source.mp4',work/'mixed_vi.wav',segments,work/'screen_text',total_duration,text_mode,command,report)
        save_json(translated,segments)
        report(1,f'Hoàn tất — {len(segments)} câu. Video đã xuất: {result.name}')
        outputs = dict(video=str(result),audio=str(work/'mixed_vi.wav'),srt=str(work/'vietnamese.srt'),segments=str(translated),log=str(log),directory=str(work))
        save_json(work/'result.json', outputs)
        return outputs
    except Exception as e:
        report(0,f'LỖI: {e}')
        raise


def mix_and_mux(work,segments,total,duck_db,log,report=lambda p,m: None,mux_video=True):
    sr=44100
    frames=round(total*sr)
    voice=np.zeros((frames,2),dtype=np.float32)
    fitted=work/'fitted'
    fitted.mkdir(exist_ok=True)
    for i,seg in enumerate(segments):
        start=max(0,float(seg['start']))
        end=min(total,float(seg.get('fit_end',seg['end'])),float(segments[i+1]['start']) if i+1<len(segments) else total)
        if end<=start:
            raise ValueError(f'Mốc thời gian không hợp lệ ở câu {i+1}')
        raw=work/'voice'/f'{i:04d}.wav'
        samples,raw_sr=sf.read(raw)
        actual=len(samples)/raw_sr
        window=end-start
        planned=min(window,float(seg.get('target_duration',window)))
        rate=actual/planned if 'target_duration' in seg else max(1.0,actual/window)
        if rate>MAX_SPEED+1e-4:
            raise RuntimeError(f'Câu {i+1} cần tăng tốc {rate:.2f}×, vượt giới hạn {MAX_SPEED:g}× trong {window:.2f}s.')
        if rate>1.05:
            report(.82,f'6/6 — Câu {i+1}: giữ lời dịch, tăng tốc {rate:.2f}× để khớp {window:.2f}s (tối đa {MAX_SPEED:g}×).')
        segment_record=segments[i]
        segment_record['audio_seconds']=round(actual,3)
        segment_record['playback_speed']=round(rate,4)
        segment_record['fitted_speech_seconds']=round(actual/rate,4)
        dest=fitted/f'{i:04d}.wav'
        command([FFMPEG,'-y','-i',raw,'-af',tempo_filters(rate)+f',apad,atrim=duration={window:.6f},afade=t=in:d=0.008,afade=t=out:st={max(0,window-.015):.6f}:d=0.015','-ar',str(sr),'-ac','2',dest],log)
        wav,_=sf.read(dest,dtype='float32',always_2d=True)
        pos=round(start*sr); n=min(len(wav),frames-pos)
        voice[pos:pos+n]+=wav[:n]
    sf.write(work/'voice_vi.wav',voice,sr,subtype='PCM_16')
    # Never mix the source vocals back in. Only bass/drums/other are retained.
    bed=np.zeros_like(voice)
    for name in ['bass','drums','other']:
        wav,stem_sr=sf.read(work/'stems'/f'{name}.wav',dtype='float32',always_2d=True)
        if stem_sr!=sr:
            raise RuntimeError(f'Unexpected stem sample rate: {stem_sr}')
        n=min(frames,len(wav)); bed[:n]+=wav[:n]
    sf.write(work/'background.wav',bed,sr,subtype='FLOAT')
    # Drive ducking from the generated Vietnamese audio, with a 15 ms attack
    # and 250 ms release. The slider is the actual reduction during speech.
    hop = max(1, round(sr * .01))
    blocks = (frames + hop - 1) // hop
    mono = voice.mean(axis=1)
    padded = np.pad(mono, (0, blocks * hop - frames))
    rms = np.sqrt(np.mean(padded.reshape(blocks, hop) ** 2, axis=1))
    gains = np.ones(blocks, dtype=np.float32)
    attenuation = 10 ** (-duck_db / 20)
    gain = 1.0
    for k, level in enumerate(rms):
        target = attenuation if level > .008 else 1.0
        tau = .015 if target < gain else .250
        gain = target + (gain - target) * np.exp(-.01 / tau)
        gains[k] = gain
    envelope = np.interp(np.arange(frames), np.arange(blocks)*hop, gains)
    mixed = bed * envelope[:, None] + voice
    peak = float(np.max(np.abs(mixed)))
    if peak > .95:
        mixed *= .95 / peak
    sf.write(work/'mixed_vi.wav', mixed, sr, subtype='PCM_16')
    if not mux_video:return work/'mixed_vi.wav'
    result=work/'video_tieng_viet.mp4'
    command([FFMPEG,'-y','-i',work/'source.mp4','-i',work/'mixed_vi.wav','-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-t',str(total),'-movflags','+faststart',result],log)
    if abs(duration(result)-total)>.25:
        raise RuntimeError('Video đầu ra lệch thời lượng quá 250 ms.')
    return result
