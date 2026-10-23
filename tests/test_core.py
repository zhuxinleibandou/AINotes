import asyncio
import json
import socket
import subprocess
from pathlib import Path
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from backend import store, worker
from backend.app import app, markdown
from backend.codex import Cancelled, GenerationError, run_process, validate_refs
from backend.extract import check_url, normalize_url, finalize, extract_file, segment, subtitle_segments, ExtractionError
from backend.models import Note, Question

@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.setattr(store,'DB',tmp_path/'test.sqlite3')
    store.init()
    worker.shutdown.clear()
    return tmp_path

@pytest.fixture
def client(db):
    return TestClient(app)

def content():
    return dict(title='验收笔记',subtitle='保留条件',overview='说明条件、数据和限制。',sections=[dict(title='步骤',kind='steps',markdown='1. 阅读\n2. 核对',keypoints=['阅读','核对'],source_ids=['s1'])],limitations=['只作演示'],conclusion='回到原文核对。')

def test_import_queue_and_search(client):
    response=client.post('/api/import',json={'kind':'text','content':'这是一份足够长的真实输入，用来测试本地资料持久化。'})
    assert response.status_code==200
    value=response.json();assert value['job']['status']=='queued'
    note=client.get('/api/notes/'+value['note']['id']).json()
    assert note['source']['content'].startswith('这是一份')
    assert client.get('/api/notes?q=真实输入').json()[0]['id']==note['id']
    assert client.post('/api/notes/'+note['id']+'/generate',json={'kind':'summary'}).status_code==409

def test_invalid_input_no_fake_success(client):
    assert client.post('/api/import',json={'kind':'text','content':'短'}).status_code==422
    assert client.post('/api/import',json={'kind':'url','content':'无效链接'}).status_code==422
    assert client.post('/api/import/file',files={'file':('bad.doc',b'x')}).status_code==422
    assert client.post('/api/import/file',files={'file':('empty.txt',b'')}).status_code==422
    assert client.get('/api/notes').json()==[]

def test_upload_and_cancel_retry(client):
    result=client.post('/api/import/file',files={'file':('../../学习.txt','这是测试材料，保存文件时不能越过指定材料目录。'.encode())}).json()
    note=result['note'];job=result['job']
    assert note['source']['filename']=='学习.txt'
    assert client.post('/api/jobs/'+job['id']+'/cancel').json()['status']=='cancelled'
    replacement=client.post('/api/jobs/'+job['id']+'/retry').json()
    assert replacement['id']!=job['id'] and replacement['status']=='queued'
    assert client.get('/api/notes/'+note['id']+'/source').content.decode().startswith('这是测试')

def test_origin_and_host_protection(client):
    payload={'kind':'text','content':'足够长的内容，应该被来源检查拦截而不创建记录。'}
    assert client.post('/api/import',json=payload,headers={'origin':'https://evil.test'}).status_code==403
    assert client.post('/api/import',json=payload,headers={'origin':'null'}).status_code==403
    assert client.get('/api/notes',headers={'host':'evil.test'}).status_code==400

def test_process_keeps_source_and_refuses_failed_generation(db,monkeypatch):
    note=store.create_note({'kind':'text','content':'足够长的材料，示例数字为10分钟，但并未提供实验结论。'},'材料')
    job=store.create_job(note['id'],'summary')
    def fail(*args,**kwargs):raise GenerationError('测试：模型不可用')
    monkeypatch.setattr(worker,'generate',fail)
    worker.process(job)
    assert store.get_job(job['id'])['status']=='failed'
    saved=store.get_note(note['id']);assert saved['segments'] and saved['note'] is None
    monkeypatch.setattr(worker,'generate',lambda *args,**kwargs:content())
    retried=store.create_job(note['id'],'summary');worker.process(retried)
    assert store.get_job(retried['id'])['status']=='completed'
    assert store.get_note(note['id'])['revision']==1

def test_versions_cas_and_progress_merge(db):
    note=store.create_note({'kind':'text','content':'正文测试材料'},'测试')
    nid=note['id'];store.update_note(nid,segments=[segment('正文','第1段')])
    store.save_note_version(nid,content(),expected=0)
    store.update_note(nid,progress={'completed':['c1'],'answers':{},'last_chapter':'c1'})
    changed=content();changed['title']='人工修改'
    store.save_note_version(nid,changed,expected=1)
    assert store.get_note(nid)['progress']['completed']==['c1']
    with pytest.raises(ValueError):store.save_note_version(nid,content(),expected=1)
    with store.connection() as con:
        assert con.execute('SELECT count(*) FROM versions').fetchone()[0]==1

def test_restart_recovery(db):
    note=store.create_note({'kind':'text','content':'正文'},'测试')
    job=store.create_job(note['id'],'summary')
    store.set_job(job['id'],status='running')
    store.init()
    assert store.get_job(job['id'])['status']=='interrupted'

def test_no_truncation_and_citation_validation():
    text='重要数据123。'*3000
    result=finalize('标题',[segment(text,'第1页')],'正文')
    assert ''.join(s['text'] for s in result['segments'])==text
    with pytest.raises(GenerationError):validate_refs({'source_ids':['fake']},{'s1'})
    with pytest.raises(GenerationError):validate_refs({'source_ids':[]},{'s1'})
    with pytest.raises(ExtractionError):finalize('空',[],'正文')

def test_normalize_platform_links():
    assert normalize_url('分享 https://www.douyin.com/user/self?modal_id=7650000000000000000&showTab=like，')=='https://www.douyin.com/video/7650000000000000000'
    assert normalize_url('https://notdouyin.com/user/self?modal_id=123')=='https://notdouyin.com/user/self?modal_id=123'

@pytest.mark.parametrize('url',['http://example.com','https://localhost','https://127.0.0.1','https://192.168.1.1','https://[::1]','https://user:pass@example.com','https://example.com:8080'])
def test_private_urls(url):
    with pytest.raises(ExtractionError):check_url(url)

def test_private_dns_and_proxy(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.2',443))])
    with pytest.raises(ExtractionError):check_url('https://example.com')
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('198.18.0.2',443))])
    assert check_url('https://example.com')
    with pytest.raises(ExtractionError):check_url('https://198.18.0.2')

def test_subtitle_timestamps():
    parts=subtitle_segments(b'WEBVTT\n\n00:00:01.200 --> 00:00:03.000\nHello world\n\n00:00:04.000 --> 00:00:06.000\nSecond line','vtt')
    assert parts[0]['start']==1.2 and parts[1]['text']=='Second line'
    data=json.dumps({'events':[{'tStartMs':1000,'dDurationMs':2000,'segs':[{'utf8':'知识点'}]}]}).encode()
    assert subtitle_segments(data,'json3')[0]['end']==3

def test_real_document_parsers(db):
    from docx import Document
    from pptx import Presentation
    from pptx.util import Inches
    import pymupdf as fitz
    path=db/'document.docx';doc=Document();doc.add_heading('阅读与核对');doc.add_paragraph('第一步是阅读，第二步是解释，第三步是核对，示例为十分钟。');doc.save(path)
    result=extract_file(path,db,lambda:False,lambda _:None)
    assert '十分钟' in ''.join(s['text'] for s in result['segments'])
    deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6]);slide.shapes.add_textbox(Inches(1),Inches(1),Inches(5),Inches(2)).text_frame.text='学习的三个步骤：阅读、解释、核对。示例数字10分钟。';path=db/'slides.pptx';deck.save(path)
    result=extract_file(path,db,lambda:False,lambda _:None)
    assert result['segments'][0]['location']=='第 1 张幻灯片'
    document=fitz.open();page=document.new_page();page.insert_text((50,50),'Real PDF parser verification. Reading, explaining and checking. 10 minutes example.');path=db/'sample.pdf';document.save(path)
    result=extract_file(path,db,lambda:False,lambda _:None)
    assert result['segments'][0]['location']=='第 1 页' and '10 minutes' in result['segments'][0]['text']

def test_text_encoding_and_broken_file(db):
    path=db/'中文.txt';path.write_bytes('中文编码测试，第三天复习，只是示例安排。'.encode('gb18030'))
    result=extract_file(path,db,lambda:False,lambda _:None)
    assert '第三天' in result['segments'][0]['text']
    path=db/'broken.pdf';path.write_bytes(b'not a pdf')
    with pytest.raises(Exception):extract_file(path,db,lambda:False,lambda _:None)

def test_answers_and_exports():
    good=dict(id='q1',kind='single',prompt='问题',options=['A','B'],correct=[0],explanation='解释',source_ids=['s1'])
    assert Question.model_validate(good)
    with pytest.raises(ValueError):Question.model_validate(good|{'correct':[3]})
    with pytest.raises(ValueError):Question.model_validate(good|{'correct':[0,1]})
    note={'note':content(),'scope':'基于原文','source':{'kind':'text'},'segments':[{'id':'s1','location':'第1段'}]}
    for kind in ('markdown','overview','outline'):
        text=markdown(note,kind)
        assert '来源片段' not in text and '来源索引' not in text and '[s1]' not in text
        assert '验收笔记' in text
    assert '只作演示' in markdown(note,'markdown')
    assert note['note']['sections'][0]['source_ids'] == ['s1']

def test_cancel_subprocess():
    import sys
    with pytest.raises(Cancelled):run_process([sys.executable,'-c','import time;time.sleep(30)'],stop=lambda:True)

def test_cancelled_job_is_not_restarted(db,monkeypatch):
    note=store.create_note({'kind':'text','content':'这是足够长的输入，不应在取消后继续处理或调用模型。'},'已取消')
    job=store.create_job(note['id'],'summary')
    store.set_job(job['id'],status='cancelled')
    never=Mock(side_effect=AssertionError('不应调用模型'))
    monkeypatch.setattr(worker,'generate',never)
    worker.process(job)
    never.assert_not_called()
    assert store.get_job(job['id'])['status']=='cancelled'

def test_regeneration_archives_learning_and_answers(db):
    note=store.create_note({'kind':'text','content':'材料'},'测试')
    nid=note['id']
    course={'title':'课程一','description':'说明','chapters':[{'id':'c1','title':'第一章','objective':'理解','source_ids':['s1']}]}
    store.save_artifact(nid,'course',course,1)
    store.save_artifact(nid,'lesson:c1',{'title':'第一章','questions':[{'id':'c1_q1'}]},1)
    store.update_note(nid,progress={'completed':['c1'],'answers':{'c1_q1':[0]},'last_chapter':'c1'})
    store.save_artifact(nid,'course',course|{'title':'课程二'},2)
    saved=store.get_note(nid)
    assert saved['progress']['completed']==[] and saved['progress']['answers']=={}
    assert 'lesson:c1' not in saved['artifacts']
    with store.connection() as con:
        rows=con.execute('SELECT progress FROM artifact_history WHERE note_id=?',(nid,)).fetchall()
    assert len(rows)==2 and json.loads(rows[0]['progress'])['completed']==['c1']

def test_cookie_scope_and_storage(client,db):
    text='# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tTRUE\t1999999999\tsession\tTEST_ONLY\n.evil.test\tTRUE\t/\tTRUE\t1999999999\tsecret\tNOT_SAVED\n'
    response=client.post('/api/settings/platform-cookies',data={'platform':'douyin'},files={'file':('cookies.txt',text.encode())})
    assert response.status_code==200
    saved=(db/'secrets'/'douyin-cookies.txt').read_text()
    assert 'TEST_ONLY' in saved and 'NOT_SAVED' not in saved
    assert (db/'secrets'/'douyin-cookies.txt').stat().st_mode&0o777==0o600
    assert client.post('/api/settings/platform-cookies',data={'platform':'youtube'},files={'file':('cookies.txt',b'invalid')}).status_code==422
    assert client.post('/api/settings/platform-cookies/douyin/remove').status_code==200
    assert not (db/'secrets'/'douyin-cookies.txt').exists()

def test_atomic_progress_merges_answers_and_refuses_stale_course(client):
    from concurrent.futures import ThreadPoolExecutor
    nid=store.create_note({'kind':'text','content':'验收正文'},'并发答题')['id']
    question=dict(id='q1',kind='single',prompt='问题',options=['甲','乙'],correct=[0],explanation='依据',source_ids=['s1'])
    store.save_artifact(nid,'quiz',{'title':'测验','questions':[question,question|{'id':'q2'}]},1)
    epoch=store.get_note(nid)['progress']['epoch']
    def answer(qid):return client.put(f'/api/notes/{nid}/progress',json={'epoch':epoch,'answers':{qid:[0]}})
    with ThreadPoolExecutor(2) as pool:
        assert all(r.status_code==200 for r in pool.map(answer,['q1','q2']))
    assert store.get_note(nid)['progress']['answers']=={'q1':[0],'q2':[0]}
    assert client.put(f'/api/notes/{nid}/progress',json={'epoch':epoch,'answers':{'q1':[7]}}).status_code==409
    assert client.put(f'/api/notes/{nid}/progress',json={'epoch':epoch,'answers':{'missing':[0]}}).status_code==409
    response=client.put(f'/api/notes/{nid}/progress',json={'epoch':epoch,'answers':{'q1':None}})
    assert response.json()['progress']['answers']=={'q2':[0]}
    store.save_artifact(nid,'quiz',{'title':'新测验','questions':[question]},1)
    assert answer('q1').status_code==409
    assert store.get_note(nid)['progress']['answers']=={}

def test_second_instance_cannot_interrupt_jobs(db):
    with store.instance_lock():
        with pytest.raises(RuntimeError,match='另一服务'):
            with store.instance_lock():pass
    with store.instance_lock():pass

def test_lesson_duplicate_questions_rejected():
    from backend.models import Lesson
    q=dict(id='q1',kind='single',prompt='问题',options=['甲','乙'],correct=[0],explanation='依据',source_ids=['s1'])
    with pytest.raises(ValueError,match='重复'):
        Lesson.model_validate(dict(title='章节',objective='理解',markdown='讲解',summary='小结',source_ids=['s1'],questions=[q,q]))

def test_provider_credentials_are_not_process_arguments(monkeypatch):
    from backend import codex
    observed={}
    monkeypatch.setattr(codex,'config',lambda:{'model_provider':'custom','model_providers':{'custom':{'name':'custom','base_url':'https://example.test','http_headers':{'Authorization':'TEST_PRIVATE_VALUE'},'experimental_bearer_token':'TEST_BEARER_VALUE'}}})
    monkeypatch.setattr(codex,'executable',lambda:'codex')
    def fake_run(args,**kwargs):
        observed.update(args=args,env=kwargs['env'])
        Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(content()))
    monkeypatch.setattr(codex,'run_process',fake_run)
    codex.generate('测试',Note,lambda:False)
    assert not any('TEST_PRIVATE_VALUE' in a or 'TEST_BEARER_VALUE' in a for a in observed['args'])
    assert observed['env']['SHIYE_PROVIDER_HEADER_0']=='TEST_PRIVATE_VALUE'
    assert observed['env']['SHIYE_PROVIDER_TOKEN']=='TEST_BEARER_VALUE'
