import threading

import pytest
from fastapi.testclient import TestClient
from backend import store, worker
from backend.app import app

@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.setattr(store, 'DB', tmp_path / 'library.sqlite3')
    store.init()
    worker.shutdown.clear()
    return tmp_path

def make_note(title='删除验收', status='completed'):
    note=store.create_note({'kind':'text','content':'这是一份独立测试笔记，验证删除不会影响其他材料。'}, title)
    job=store.create_job(note['id'], 'summary')
    store.set_job(job['id'], status=status)
    return note,job

def content(title):
    return dict(title=title,subtitle='验收',overview='检查全部记录清理。',sections=[],limitations=[],conclusion='仅用于测试。')

def test_delete_removes_all_history_and_owned_files_only(db):
    client=TestClient(app)
    original=db.parent/'external-original.txt';original.write_text('外部原件仍保留。')
    imported=client.post('/api/import/file',files={'file':('原材料.txt',original.read_bytes())}).json()
    ident=imported['note']['id'];client.post('/api/jobs/'+imported['job']['id']+'/cancel')
    for title in ('第一版','第二版'):store.save_note_version(ident,content(title))
    for title in ('旧课程','新课程'):store.save_artifact(ident,'course',{'title':title,'chapters':[]},2)
    materials=db/'materials'/ident
    for name in ('chunk-cache.json','transcript.json','frames/0.00.jpg'):
        p=materials/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('验收数据')
    assert client.get(f'/api/notes/{ident}/export/markdown').status_code==200
    assert client.post(f'/api/notes/{ident}/exports',data={'revision':2},files={'file':('长图.png',b'export-test')}).status_code==200
    other,_=make_note('保留的笔记');other_folder=db/'materials'/other['id'];other_folder.mkdir(parents=True);(other_folder/'source.txt').write_text('保留')
    secrets=db/'secrets';secrets.mkdir();(secrets/'model-test.json').write_text('TEST_ONLY')
    with store.connection() as con:
        assert con.execute('SELECT count(*) FROM versions WHERE note_id=?',(ident,)).fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM artifact_history WHERE note_id=?',(ident,)).fetchone()[0]==1
    assert client.delete('/api/notes/'+ident).status_code==200
    for url in (f'/api/notes/{ident}',f'/api/notes/{ident}/versions',f'/api/notes/{ident}/learning-history',f'/api/notes/{ident}/source',f'/api/jobs/{imported["job"]["id"]}/retry'):
        response=client.post(url) if url.endswith('/retry') else client.get(url)
        assert response.status_code==404
    assert not materials.exists() and not (db/'exports'/ident).exists()
    with store.connection() as con:
        for table in ('jobs','versions','artifact_history'):
            assert con.execute(f'SELECT count(*) FROM {table} WHERE note_id=?',(ident,)).fetchone()[0]==0
    assert original.read_text()=='外部原件仍保留。'
    assert store.get_note(other['id'])['title']=='保留的笔记'
    assert (other_folder/'source.txt').read_text()=='保留'
    assert (secrets/'model-test.json').read_text()=='TEST_ONLY'
    assert client.get('/api/notes').json()[0]['id']==other['id']

@pytest.mark.parametrize('status',['queued','running','pausing','cancelling'])
def test_active_task_must_really_stop_before_deletion(db,status):
    note,job=make_note(status=status);client=TestClient(app)
    folder=db/'materials'/note['id'];folder.mkdir(parents=True);(folder/'source').write_text('保留')
    info=client.get('/api/notes/'+note['id']+'/delete-info').json()
    assert info['active_job']=={'id':job['id'],'status':status,'stage':job['stage']}
    response=client.delete('/api/notes/'+note['id'])
    assert response.status_code==409 and '停止' in response.text
    assert folder.exists() and store.get_note(note['id'])

@pytest.mark.parametrize('status',['paused','cancelled','interrupted','failed','completed'])
def test_settled_tasks_can_be_deleted_and_cannot_be_resurrected(db,status):
    note,job=make_note(status=status);client=TestClient(app)
    assert client.get('/api/notes/'+note['id']+'/delete-info').json()['active_job'] is None
    assert client.delete('/api/notes/'+note['id']).status_code==200
    with pytest.raises(KeyError):store.create_job(note['id'],'summary')
    assert store.next_job() is None
    worker.process(job)  # A worker holding an old queue snapshot cannot claim a deleted job.
    assert not (db/'materials'/note['id']).exists()
    assert client.post('/api/settings/resume-tasks').json()['resumed']==0
    assert client.delete('/api/notes/'+note['id']).status_code==404

def test_failed_file_cleanup_retains_records_for_retry(db,monkeypatch):
    note,_=make_note();folder=db/'materials'/note['id'];folder.mkdir(parents=True);(folder/'source.txt').write_text('保留')
    client=TestClient(app)
    with monkeypatch.context() as patch:
        patch.setattr(store.shutil,'rmtree',lambda p:(_ for _ in ()).throw(PermissionError('TEST_ONLY')))
        response=client.delete('/api/notes/'+note['id'])
        assert response.status_code==409 and '记录已保留' in response.text
    assert store.get_note(note['id']) and (folder/'source.txt').exists()
    assert client.delete('/api/notes/'+note['id']).status_code==200

def test_symlinks_never_delete_external_targets(db):
    outside=db.parent/'outside-delete-test';outside.mkdir();(outside/'keep.txt').write_text('外部文件')
    note,_=make_note();(db/'materials').mkdir();(db/'materials'/note['id']).symlink_to(outside,target_is_directory=True)
    store.delete_note(note['id']);assert (outside/'keep.txt').read_text()=='外部文件'
    note,_=make_note();(db/'exports').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='外部链接'):store.delete_note(note['id'])
    assert store.get_note(note['id']) and (outside/'keep.txt').exists()

@pytest.mark.parametrize('mode',['markdown','image'])
def test_late_export_cannot_recreate_deleted_files(db,monkeypatch,mode):
    note,_=make_note();ident=note['id'];store.save_note_version(ident,content('延迟导出'))
    write=store.write_export
    def delayed_write(ident,filename,data):
        store.delete_note(ident);write(ident,filename,data)
    monkeypatch.setattr(store,'write_export',delayed_write)
    client=TestClient(app)
    response=client.get(f'/api/notes/{ident}/export/markdown') if mode=='markdown' else client.post(f'/api/notes/{ident}/exports',data={'revision':1},files={'file':('long.png',b'PNG')})
    assert response.status_code==404 and not (db/'exports'/ident).exists()

def test_create_job_waits_for_deletion_transaction(db,monkeypatch):
    note,_=make_note();folder=db/'materials'/note['id'];folder.mkdir(parents=True)
    entered=threading.Event();release=threading.Event();results=[]
    remove=store.shutil.rmtree
    def slow_remove(path):entered.set();assert release.wait(3);remove(path)
    monkeypatch.setattr(store.shutil,'rmtree',slow_remove)
    deleting=threading.Thread(target=store.delete_note,args=(note['id'],));deleting.start();assert entered.wait(3)
    def enqueue():
        try:store.create_job(note['id'],'summary');results.append('unexpected')
        except KeyError:results.append('missing')
    adding=threading.Thread(target=enqueue);adding.start()
    release.set();deleting.join(3);adding.join(3)
    assert not deleting.is_alive() and not adding.is_alive() and results==['missing']

def test_orphaned_file_note_can_be_removed_but_external_origin_cannot_delete(db):
    note=store.create_note({'kind':'file','filename':'import.txt'},'正在导入')
    client=TestClient(app)
    assert client.delete('/api/notes/'+note['id'],headers={'origin':'https://external.example.test'}).status_code==403
    assert store.get_note(note['id'])
    assert client.delete('/api/notes/'+note['id']).status_code==200

def test_file_note_not_visible_until_source_is_ready(db,monkeypatch):
    temp=db/'upload.tmp';temp.write_text('上传验收')
    move=store.shutil.move
    def move_before_publish(source,target):
        with pytest.raises(KeyError):store.get_note(target.parent.parent.name)
        assert not store.list_notes()
        return move(source,target)
    monkeypatch.setattr(store.shutil,'move',move_before_publish)
    note=store.create_note({'kind':'file','filename':'sample.txt'},'导入并发检查',source_file=temp)
    assert (db/'materials'/note['id']/'source/sample.txt').read_text()=='上传验收'
    store.delete_note(note['id'])
    assert not (db/'materials'/note['id']).exists()
