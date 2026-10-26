"""Local Vietnamese dubber: visible progress, one job at a time, downloadable results."""
import argparse
import json
import queue
import threading
import time
from pathlib import Path
import gradio as gr
from local_dub.pipeline import ROOT, run


def latest_result():
    saved=sorted((ROOT/'data/local_dub').glob('*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not saved:
        raise gr.Error('Chưa có video hoàn tất.')
    result=json.loads(saved[0].read_text())
    return result['video'],result['audio'],result['srt'],result['log'],'**Đã mở kết quả lưu gần nhất.**'


def process(video,reference,reference_text,duck,steps):
    if not video:
        raise gr.Error('Hãy tải video lên trước.')
    events=queue.Queue()
    def task():
        try:
            result=run(video,reference,reference_text,duck,int(steps),emit=lambda p,m: events.put(('progress',p,m)))
            events.put(('done',result))
        except Exception as e:
            events.put(('error',str(e)))
    thread=threading.Thread(target=task,daemon=True)
    thread.start()
    yield None,None,None,None,'**Đang bắt đầu xử lý…**',''
    history=[]
    started=time.monotonic()
    while True:
        try:
            event=events.get(timeout=1)
        except queue.Empty:
            if history:
                yield gr.skip(),gr.skip(),gr.skip(),gr.skip(),f"**Đang xử lý — {time.monotonic()-started:.0f} giây**\n\n{history[-1]}","\n".join(history[-50:])
            continue
        if event[0]=='progress':
            _,p,msg=event
            history.append(msg)
            yield gr.skip(),gr.skip(),gr.skip(),gr.skip(),f'**{round(p*100)}% — {msg}**','\n'.join(history[-50:])
        elif event[0]=='done':
            result=event[1]
            yield result['video'],result['audio'],result['srt'],result['log'],'**Hoàn tất — video tiếng Việt đã sẵn sàng.**','\n'.join(history[-50:])
            return
        else:
            history.append(event[1])
            yield gr.skip(),gr.skip(),gr.skip(),gr.skip(),'**Xử lý thất bại — xem chi tiết bên dưới.**','\n'.join(history[-50:])
            return


def build():
    with gr.Blocks(title='Lồng tiếng Trung → Việt') as app:
        gr.Markdown('# Video Trung → Việt\nTách lời Trung, dịch và lồng giọng Việt bằng OmniVoice. Giữ nền, hạ nhạc khi có lời nói và xuất MP4.')
        with gr.Row():
            with gr.Column():
                video=gr.Video(label='Video gốc (tối đa 5 phút)',sources=['upload'])
                with gr.Accordion('Giọng đọc và âm lượng',open=False):
                    reference=gr.Audio(label='Mẫu giọng tùy chọn (3–10 giây rõ tiếng; ưu tiên mẫu tiếng Việt)',type='filepath')
                    text=gr.Textbox(label='Lời nói chính xác trong mẫu giọng',placeholder='Bỏ trống cả hai để OmniVoice tự tạo giọng.')
                    duck=gr.Slider(0,18,value=9,step=1,label='Mức hạ nhạc nền khi nói (dB)')
                    steps=gr.Dropdown([16,32],value=16,label='Chất lượng giọng (32 chậm hơn)')
                gr.Markdown('Nhận diện, dịch bằng Qwen3 và tạo giọng chạy hoàn toàn trên máy; không gửi nội dung ra dịch vụ ngoài. Lần đầu cần Internet để tải model. Tách nhạc có thể còn sót giọng ở video nhiều tiếng ồn.')
                button=gr.Button('Tạo video tiếng Việt',variant='primary')
                reopen=gr.Button('Mở kết quả đã lưu gần nhất')
            with gr.Column():
                out=gr.Video(label='Video tiếng Việt')
                audio=gr.Audio(label='Âm thanh tiếng Việt',type='filepath')
                srt=gr.File(label='Phụ đề tiếng Việt (.srt)')
                log=gr.File(label='Tải nhật ký xử lý')
        status=gr.Markdown('Sẵn sàng.')
        details=gr.Textbox(label='Tiến độ chi tiết',lines=12,interactive=False)
        button.click(process,[video,reference,text,duck,steps],[out,audio,srt,log,status,details],concurrency_limit=1,concurrency_id='dub',show_progress='minimal')
        reopen.click(latest_result,outputs=[out,audio,srt,log,status])
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=7860)
    args=parser.parse_args()
    build().queue(default_concurrency_limit=1).launch(server_name='127.0.0.1',server_port=args.port,allowed_paths=[str(ROOT/'data/local_dub')])
