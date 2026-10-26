import concurrent.futures
import tempfile
import threading
import time
import unittest
from pathlib import Path
from local_dub.job_store import JobStore
from local_dub.queue_runner import QueueRunner

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=JobStore(self.root/'queue.db')
    def tearDown(self):self.tmp.cleanup()
    def test_retrying_same_upload_request_is_idempotent(self):
        barrier=threading.Barrier(4)
        def submit(i):barrier.wait();return self.store.enqueue('same.mp4',{},'same-content-and-settings',submission_id='same-upload-request')
        with concurrent.futures.ThreadPoolExecutor(4) as pool:results=list(pool.map(submit,range(4)))
        self.assertEqual(len({j['id'] for j,reused in results}),1)
        self.assertEqual(sum(not reused for j,reused in results),1)
        self.assertEqual(len(self.store.list()),1)
    def test_old_video_submitted_again_always_creates_new_run(self):
        first,_=self.store.enqueue('same.mp4',{},'same')
        self.store.patch(first['id'],status='done')
        second,reused=self.store.enqueue('same.mp4',{},'same')
        self.assertFalse(reused)
        self.assertNotEqual(first['id'],second['id'])
        self.assertNotEqual(first['args']['generation_id'],second['args']['generation_id'])

    def test_single_worker_fifo_and_retry_goes_to_back(self):
        first,_=self.store.enqueue('first',{},'1');second,_=self.store.enqueue('second',{},'2')
        self.store.cancel(first['id']);self.store.retry(first['id'])
        claimed=self.store.claim();self.assertEqual(claimed['id'],second['id'])
        self.assertIsNone(self.store.claim())
        self.store.patch(second['id'],status='done')
        self.assertEqual(self.store.claim()['id'],first['id'])
    def test_restart_preserves_pause_and_recovers_progress(self):
        job,_=self.store.enqueue('video',{},'x');self.store.claim();self.store.progress(job['id'],.6,'Tạo giọng 4/10')
        self.store.pause(True)
        reopened=JobStore(self.root/'queue.db');reopened.recover()
        self.assertTrue(reopened.paused());self.assertIsNone(reopened.claim())
        self.assertEqual(reopened.get(job['id'])['progress'],.6)
        reopened.pause(False);self.assertEqual(reopened.claim()['id'],job['id'])
    def test_stop_saves_current_job_without_starting_next(self):
        job,_=self.store.enqueue('video',{'video':'test'},'x')
        entered=threading.Event()
        def processor(cancel_event,emit,**args):
            emit(.52,'Tạo giọng');entered.set()
            if cancel_event.wait(5):raise InterruptedError()
            self.fail('Cancellation did not arrive')
        runner=QueueRunner(self.store,processor,self.root/'results');runner.start()
        try:self.assertTrue(entered.wait(3));runner.stop()
        finally:
            if runner.thread.is_alive():runner.stop()
        self.assertEqual(self.store.get(job['id'])['status'],'queued')
        self.assertEqual(self.store.get(job['id'])['progress'],.52)


class ProcessCancellationTests(unittest.TestCase):
    def test_cancelling_stops_a_model_process_even_without_stdout(self):
        import os
        import sys
        import local_dub.pipeline as pipeline
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);pidfile=root/'pid';event=threading.Event();errors=[]
            script=f"import os,time;open({str(pidfile)!r},'w').write(str(os.getpid()));time.sleep(60)"
            def task():
                pipeline._CANCEL.event=event
                try:list(pipeline.stream_command([sys.executable,'-c',script],root/'log'))
                except InterruptedError:errors.append('cancelled')
            thread=threading.Thread(target=task);thread.start()
            for _ in range(100):
                if pidfile.exists():break
                time.sleep(.02)
            self.assertTrue(pidfile.exists())
            pid=int(pidfile.read_text());event.set();thread.join(timeout=3)
            self.assertFalse(thread.is_alive());self.assertEqual(errors,['cancelled'])
            with self.assertRaises(ProcessLookupError):os.kill(pid,0)

if __name__=='__main__':unittest.main()
