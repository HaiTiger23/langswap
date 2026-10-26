"""One cancellable worker; snapshots outputs so later jobs cannot overwrite history."""
import logging
import shutil
import threading
import time
from pathlib import Path

class QueueRunner:
    def __init__(self,store,processor,results_root):
        self.store=store;self.processor=processor;self.results_root=Path(results_root)
        self.stopping=threading.Event();self.wake=threading.Event();self.guard=threading.Lock()
        self.current=None;self.cancel_event=None
        self.thread=threading.Thread(target=self.loop,daemon=True)
    def start(self):self.store.recover();self.thread.start()
    def notify(self):self.wake.set()
    def cancel(self,job_id):
        with self.guard:
            if self.current==job_id and self.cancel_event:self.cancel_event.set()
        self.wake.set()
    def stop(self):
        self.stopping.set()
        with self.guard:
            if self.cancel_event:self.cancel_event.set()
        self.wake.set();self.thread.join(timeout=15)
        if self.thread.is_alive():raise RuntimeError('Worker chưa dừng xong.')
    def loop(self):
        while not self.stopping.is_set():
            with self.guard:
                job=self.store.claim()
                if job:
                    self.current=job['id'];self.cancel_event=threading.Event()
            if not job:
                self.wake.wait(.5);self.wake.clear();continue
            try:
                def emit(p,m):
                    if self.stopping.is_set() or self.cancel_event.is_set():raise InterruptedError('Đã yêu cầu dừng.')
                    self.store.progress(job['id'],p,m)
                result=self.processor(**job['args'],emit=emit,cancel_event=self.cancel_event)
                if self.cancel_event.is_set():raise InterruptedError()
                folder=self.results_root/job['id'];folder.mkdir(parents=True,exist_ok=True)
                saved={'directory':str(folder),'cache_directory':result['directory'],'source':job['args']['video']}
                for kind in ['video','audio','srt','log','segments']:
                    src=Path(result[kind]);dest=folder/src.name
                    temp=dest.with_suffix(dest.suffix+'.partial');shutil.copy2(src,temp);temp.replace(dest)
                    saved[kind]=str(dest)
                self.store.patch(job['id'],status='done',progress=1,message='Video tiếng Việt đã sẵn sàng.',result=saved,finished=time.time())
            except InterruptedError:
                state='queued' if self.stopping.is_set() and not self.store.get(job['id']).get('cancel_requested') else 'cancelled'
                self.store.patch(job['id'],status=state,message='Đã lưu tiến độ; chờ khởi động lại.' if state=='queued' else 'Đã hủy. Các bước đã hoàn tất vẫn được lưu.',finished=None if state=='queued' else time.time())
            except Exception as e:
                logging.getLogger('studio').exception('Job %s failed',job['id'])
                self.store.patch(job['id'],status='error',message=str(e),finished=time.time())
            finally:
                with self.guard:self.current=None;self.cancel_event=None
