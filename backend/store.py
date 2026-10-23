import json
import os
import sqlite3
import time
import uuid
import fcntl
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('QUICKLEARN_DATA', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
os.chmod(DATA, 0o700)
DB = DATA / 'library.sqlite3'

def now():
    return time.time()

def uid():
    return uuid.uuid4().hex

def connection():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con

@contextmanager
def instance_lock():
    # A second server must not interrupt the first server's durable jobs.
    with (DATA / '.instance.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('这个资料库已在另一服务中打开，请先关闭原服务。') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)

def init():
    with connection() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, note_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL, error TEXT NOT NULL, args TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, note_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS artifact_history(id TEXT PRIMARY KEY, note_id TEXT NOT NULL, artifact_key TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL, progress TEXT NOT NULL, created REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created);
        ''')
        con.execute("UPDATE jobs SET status='interrupted', stage='服务已重启，可继续处理', updated=? WHERE status='running'", (now(),))
        con.execute("UPDATE jobs SET status='paused', stage='已暂停，可以继续处理', updated=? WHERE status='pausing'", (now(),))
        con.execute("UPDATE jobs SET status='cancelled', stage='已取消', updated=? WHERE status='cancelling'", (now(),))

def create_note(source, title, instructions='', fmt='poster', mode='summary'):
    ident = uid()
    body = dict(id=ident, title=title or '正在整理材料', source=source, instructions=instructions,
                format=fmt, mode=mode, segments=[], scope='', warnings=[], note=None, revision=0,
                artifacts={}, artifact_revisions={}, progress={'completed': [], 'answers': {}, 'last_chapter': ''})
    with connection() as con:
        con.execute('INSERT INTO notes VALUES(?,?,?,?,?)', (ident, body['title'], json.dumps(body, ensure_ascii=False), now(), now()))
    return get_note(ident)

def get_note(ident):
    with connection() as con:
        row = con.execute('SELECT * FROM notes WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise KeyError(ident)
    return {**json.loads(row['body']), 'created': row['created'], 'updated': row['updated']}

def update_note(ident, **changes):
    # Read/merge/write under one transaction so UI progress cannot overwrite a worker result.
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT body FROM notes WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise KeyError(ident)
        body = json.loads(row['body'])
        body.update(changes)
        con.execute('UPDATE notes SET title=?, body=?, updated=? WHERE id=?',
                    (body['title'], json.dumps(body, ensure_ascii=False), now(), ident))
    return get_note(ident)

def save_note_version(ident, generated, expected=None):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT body FROM notes WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise KeyError(ident)
        body = json.loads(row['body'])
        if expected is not None and body['revision'] != expected:
            raise ValueError('内容已更新，请重新打开后再保存。')
        if body.get('note'):
            con.execute('INSERT INTO versions VALUES(?,?,?,?,?)', (uid(), ident, body['revision'], json.dumps(body['note'], ensure_ascii=False), now()))
        body.update(note=generated, title=generated['title'], revision=body['revision'] + 1)
        con.execute('UPDATE notes SET title=?, body=?, updated=? WHERE id=?', (body['title'], json.dumps(body, ensure_ascii=False), now(), ident))
    return get_note(ident)

def list_notes(query=''):
    with connection() as con:
        rows = con.execute('SELECT * FROM notes WHERE title LIKE ? ORDER BY updated DESC', (f'%{query}%',)).fetchall()
    out = []
    for row in rows:
        body = json.loads(row['body'])
        source = body['source']
        if source['kind'] == 'text':
            source = {'kind':'text'}
        out.append({k: body.get(k) for k in ('id','title','source','scope','revision','format','progress')} | {
            'source':source,
            'created': row['created'], 'updated': row['updated'], 'ready': bool(body.get('note')),
            'subtitle': (body.get('note') or {}).get('subtitle',''), 'job': latest_job(row['id'])})
    return out

def create_job(note_id, kind, args=None):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        active = con.execute("SELECT * FROM jobs WHERE note_id=? AND status IN ('queued','running','pausing','cancelling')", (note_id,)).fetchone()
        if active:
            raise ValueError('这份材料已有任务正在处理，请先等待或取消。')
        ident = uid()
        con.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)', (ident, note_id, kind, 'queued', '等待处理', '', json.dumps(args or {}), now(), now()))
    return get_job(ident)

def get_job(ident):
    with connection() as con:
        row = con.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone()
    if row is None:
        raise KeyError(ident)
    return dict(row) | {'args': json.loads(row['args'])}

def latest_job(note_id):
    with connection() as con:
        row = con.execute('SELECT id FROM jobs WHERE note_id=? ORDER BY created DESC LIMIT 1', (note_id,)).fetchone()
    return get_job(row['id']) if row else None

def set_job(ident, **changes):
    allowed = {'status','stage','error'}
    if not changes.keys() <= allowed:
        raise ValueError('不支持的任务字段')
    with connection() as con:
        con.execute('UPDATE jobs SET ' + ','.join(f'{key}=?' for key in changes) + ',updated=? WHERE id=?', (*changes.values(), now(), ident))

def next_job():
    with connection() as con:
        row = con.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
    return get_job(row['id']) if row else None

def active_tasks():
    with connection() as con:
        rows=con.execute("SELECT j.id,j.note_id,j.status,j.stage,n.title FROM jobs j JOIN notes n ON n.id=j.note_id WHERE j.status IN ('queued','running','pausing','cancelling') ORDER BY j.created").fetchall()
    return [dict(r) for r in rows]

def paused_tasks():
    with connection() as con:
        return [r['id'] for r in con.execute("SELECT j.id FROM jobs j WHERE j.status='paused' AND NOT EXISTS(SELECT 1 FROM jobs later WHERE later.note_id=j.note_id AND later.created>j.created)").fetchall()]

def pause_tasks():
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("UPDATE jobs SET status='paused',stage='已暂停，可以继续处理',updated=? WHERE status='queued'",(now(),))
        con.execute("UPDATE jobs SET status='pausing',stage='正在暂停，等待当前处理停止',updated=? WHERE status='running'",(now(),))

def resume_tasks():
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        ids=paused_tasks()
        for ident in ids:
            con.execute("UPDATE jobs SET status='queued',stage='等待处理',updated=? WHERE id=? AND status='paused'",(now(),ident))
    return len(ids)

def settings():
    with connection() as con:
        row = con.execute('SELECT body FROM settings WHERE id=1').fetchone()
    return json.loads(row['body']) if row else {'whisper_model': 'mlx-community/whisper-large-v3-turbo', 'model': ''}

def save_settings(body):
    with connection() as con:
        con.execute('INSERT OR REPLACE INTO settings VALUES(1,?)', (json.dumps(body),))


def claim_job(ident):
    with connection() as con:
        changed=con.execute("UPDATE jobs SET status='running',stage='开始处理',error='',updated=? WHERE id=? AND status='queued'",(now(),ident)).rowcount
    return changed==1

def save_artifact(ident,key,result,revision):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT body FROM notes WHERE id=?',(ident,)).fetchone()
        if not row: raise KeyError(ident)
        body=json.loads(row['body']); arts=body['artifacts']; revs=body['artifact_revisions']
        affected=[k for k in arts if k==key or (key=='course' and (k.startswith('lesson:') or k.startswith('stage:')))]
        existing_ids = {q['id'] for k,a in arts.items() if k not in affected for q in a.get('questions',[])}
        if any(q['id'] in existing_ids for q in result.get('questions',[])):
            raise ValueError('生成的题目编号与已有题目重复，请重新生成。')
        for previous in affected:
            con.execute('INSERT INTO artifact_history VALUES(?,?,?,?,?,?,?)',(uid(),ident,previous,revs.get(previous,revision),json.dumps(arts[previous],ensure_ascii=False),json.dumps(body['progress']),now()))
            old=arts.pop(previous);revs.pop(previous,None)
            for question in old.get('questions',[]):body['progress']['answers'].pop(question['id'],None)
        if key=='course':
            body['progress'].update(completed=[],last_chapter='')
        body['progress']['epoch']=body['progress'].get('epoch',0)+1
        arts[key]=result;revs[key]=revision
        con.execute('UPDATE notes SET body=?,updated=? WHERE id=?',(json.dumps(body,ensure_ascii=False),now(),ident))
    return get_note(ident)


def complete_job(ident):
    with connection() as con:
        con.execute("UPDATE jobs SET status='completed',stage='整理完成',updated=? WHERE id=? AND status='running'",(now(),ident))


def patch_progress(ident, request):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT body FROM notes WHERE id=?',(ident,)).fetchone()
        if not row: raise KeyError(ident)
        body = json.loads(row['body'])
        progress = body['progress']
        if request.epoch != progress.get('epoch',0):
            raise ValueError('课程或题目已经更新，请刷新后再保存进度。')
        chapters = {c['id'] for c in body['artifacts'].get('course',{}).get('chapters',[])}
        if not set(request.completed) <= chapters or (request.last_chapter and request.last_chapter not in chapters):
            raise ValueError('学习进度包含不存在的章节。')
        questions = {q['id']:q for artifact in body['artifacts'].values() for q in artifact.get('questions',[])}
        for ident_q, answer in request.answers.items():
            question = questions.get(ident_q)
            if question is None: raise ValueError('这道题目已经不存在，请刷新后重试。')
            if answer is not None:
                if not answer or len(set(answer)) != len(answer) or any(i < 0 or i >= len(question['options']) for i in answer):
                    raise ValueError('答案包含无效选项。')
                if question['kind'] != 'multiple' and len(answer) != 1:
                    raise ValueError('单选和判断题只能选择一个选项。')
                progress['answers'][ident_q] = answer
            else:
                progress['answers'].pop(ident_q,None)
        progress['completed'] = list(dict.fromkeys(progress['completed']+request.completed))
        if request.last_chapter is not None: progress['last_chapter'] = request.last_chapter
        con.execute('UPDATE notes SET body=?,updated=? WHERE id=?',(json.dumps(body,ensure_ascii=False),now(),ident))
    return get_note(ident)
