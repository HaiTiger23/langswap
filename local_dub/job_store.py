"""Durable, atomic FIFO queue shared by every browser tab."""
import json
import sqlite3
import time
import uuid
from pathlib import Path

ACTIVE=('queued','running')

class JobStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS jobs (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE,fingerprint TEXT,status TEXT,created REAL,data TEXT)')
            if 'submission' not in {r['name'] for r in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN submission TEXT')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS job_submission ON jobs(submission)')
            db.execute('CREATE INDEX IF NOT EXISTS queue_status ON jobs(status,seq)')
            db.execute('CREATE INDEX IF NOT EXISTS queue_fingerprint ON jobs(fingerprint,status)')
            db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT)')
    def connect(self):
        db=sqlite3.connect(self.path,timeout=20);db.row_factory=sqlite3.Row
        return db
    def _write(self,db,job):
        db.execute('UPDATE jobs SET status=?,created=?,data=? WHERE id=?',(job['status'],job.get('queued_at',job['created']),json.dumps(job,ensure_ascii=False),job['id']))
    def enqueue(self,name,args,fingerprint,submission_id=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if submission_id:
                old=db.execute('SELECT data FROM jobs WHERE submission=?',(submission_id,)).fetchone()
                if old:return json.loads(old['data']),True
            job_id=uuid.uuid4().hex
            args=dict(args,generation_id=job_id)
            job=dict(id=job_id,name=name,args=args,fingerprint=fingerprint,status='queued',progress=0,message='Đang chờ đến lượt.',history=[],created=time.time(),attempts=0)
            db.execute('INSERT INTO jobs(id,fingerprint,status,created,data,submission) VALUES(?,?,?,?,?,?)',(job['id'],fingerprint,'queued',job['created'],json.dumps(job,ensure_ascii=False),submission_id))
            return job,False
    def get(self,job_id):
        with self.connect() as db:
            row=db.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
            return json.loads(row['data']) if row else None
    def list(self):
        with self.connect() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM jobs ORDER BY seq DESC LIMIT 1000')]
    def patch(self,job_id,**values):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row: return None
            job=json.loads(row['data']);job.update(values);self._write(db,job);return job
    def progress(self,job_id,progress,message):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
            job=json.loads(row['data']);job.update(progress=progress,message=message)
            job['history']=(job.get('history',[])+[message])[-300:]
            self._write(db,job)
    def paused(self):
        with self.connect() as db:
            row=db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            return bool(row and row['value']=='true')
    def pause(self,value):
        with self.connect() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('paused',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('true' if value else 'false',))
    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            paused=db.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
            if paused and paused['value']=='true': return None
            if db.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone(): return None
            row=db.execute("SELECT data FROM jobs WHERE status='queued' ORDER BY created,seq LIMIT 1").fetchone()
            if not row:return None
            job=json.loads(row['data']);job.update(status='running',started=time.time(),finished=None,cancel_requested=False,attempts=job.get('attempts',0)+1,message='Tiếp tục từ dữ liệu đã lưu.' if job.get('attempts',0) else 'Bắt đầu xử lý.')
            self._write(db,job);return job
    def recover(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute("SELECT data FROM jobs WHERE status='running'").fetchall():
                job=json.loads(row['data'])
                if job.get('cancel_requested'):
                    job.update(status='cancelled',finished=time.time(),message='Đã hủy tác vụ.')
                else:
                    job.update(status='queued',message='Đã lưu tiến độ; sẽ tiếp tục từ các bước đã xong.')
                self._write(db,job)
    def cancel(self,job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row:return None
            job=json.loads(row['data'])
            if job['status']=='queued':job.update(status='cancelled',finished=time.time(),message='Đã hủy khỏi hàng đợi.')
            elif job['status']=='running':job.update(cancel_requested=True,message='Đang dừng xử lý và lưu các bước đã hoàn tất…')
            self._write(db,job);return job
    def retry(self,job_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row:return None
            job=json.loads(row['data'])
            if job['status'] not in ('error','cancelled'):return job
            duplicate=db.execute("SELECT data FROM jobs WHERE fingerprint=? AND status IN ('queued','running') AND id!=?",(job.get('fingerprint'),job_id)).fetchone()
            if duplicate:return json.loads(duplicate['data'])
            job.update(status='queued',queued_at=time.time(),cancel_requested=False,finished=None,message='Chờ chạy lại từ dữ liệu đã lưu.')
            self._write(db,job);return job
    def import_result(self,job):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO jobs(id,fingerprint,status,created,data) VALUES(?,?,?,?,?)',(job['id'],None,'done',job['created'],json.dumps(job,ensure_ascii=False)))
