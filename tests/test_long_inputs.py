import json
import re
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from backend import store, worker, extract as extraction, douyin
from backend.app import app
from backend.codex import Cancelled
from backend.extract import (MediaTooLong, ExtractionError, MAX_LINK_SECONDS, link_duration,
                             probe_duration, extract, finalize, segment, media_url, transcribe)

@pytest.fixture
def library(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.setattr(store,'DB',tmp_path/'library.sqlite3')
    store.init()
    worker.shutdown.clear()
    return tmp_path

@pytest.mark.parametrize('duration',[35999.9,36000,'36000'])
def test_link_allows_600_minutes(duration):
    assert link_duration(duration) == float(duration)

@pytest.mark.parametrize('duration',[36000.001,36001,72000])
def test_link_rejects_over_600_minutes(duration):
    with pytest.raises(MediaTooLong,match='600分钟'): link_duration(duration)

@pytest.mark.parametrize('duration',[None,'N/A','nan','inf',0,-1])
def test_unknown_duration_is_not_a_verified_duration(duration):
    assert link_duration(duration) is None

@pytest.mark.parametrize('duration,allowed',[(36000,True),(36000.01,False)])
def test_platform_checks_duration_before_subtitles(tmp_path,monkeypatch,duration,allowed):
    monkeypatch.setattr(extraction,'run_process',lambda *a,**kw:json.dumps({'title':'边界音频','duration':duration,'subtitles':{'zh':[{'ext':'json3','url':'https://example.com/sub'}]}}).encode())
    fetched=[]
    def fetch(*a,**kw):
        fetched.append(a)
        return json.dumps({'events':[{'tStartMs':0,'dDurationMs':1000,'segs':[{'utf8':'这是一段真实字幕格式的边界测试材料，不应截断或冒充成功。'}]}]}).encode(),'',''
    monkeypatch.setattr(extraction,'fetch',fetch)
    if allowed:
        assert media_url('https://www.youtube.com/watch?v=test',tmp_path,lambda:False,lambda _:None)['segments']
        assert len(fetched)==1
    else:
        with pytest.raises(MediaTooLong):media_url('https://www.youtube.com/watch?v=test',tmp_path,lambda:False,lambda _:None)
        assert not fetched

@pytest.mark.parametrize('url',['https://example.com/recording.mp3','https://www.xiaoyuzhoufm.com/episode/test'])
def test_downloaded_links_checked_before_transcription(library,monkeypatch,url):
    monkeypatch.setattr(extraction,'check_url',lambda url:url)
    def fetch(url,**kwargs):
        if kwargs.get('destination'):kwargs['destination'].write_bytes(b'placeholder');return b'',url,'audio/mp4'
        return b'<html><title>Podcast</title><audio src="https://example.com/podcast.m4a"></audio></html>',url,'text/html'
    monkeypatch.setattr(extraction,'fetch',fetch)
    monkeypatch.setattr(extraction,'probe_duration',lambda *args:36001)
    monkeypatch.setattr(extraction,'transcribe',lambda *args:pytest.fail('Overlong link reached ASR'))
    with pytest.raises(MediaTooLong):extract({'id':'test','source':{'kind':'url','content':url}},lambda:False,lambda _:None)

def test_unknown_platform_duration_requires_download_probe(tmp_path,monkeypatch):
    def process(args,**kwargs):
        if '--dump-single-json' in args:return b'{"title":"unknown","subtitles":{}}'
        (tmp_path/'media.m4a').write_bytes(b'placeholder')
        return b''
    monkeypatch.setattr(extraction,'run_process',process)
    monkeypatch.setattr(extraction,'probe_duration',lambda *args:36001)
    monkeypatch.setattr(extraction,'transcribe',lambda *args:pytest.fail('Overlong link reached ASR'))
    with pytest.raises(MediaTooLong):media_url('https://www.youtube.com/watch?v=test',tmp_path,lambda:False,lambda _:None)

def test_douyin_duration_cannot_fall_back(tmp_path,monkeypatch):
    monkeypatch.setattr(douyin,'public_video',lambda *args:(_ for _ in ()).throw(MediaTooLong('600分钟')))
    monkeypatch.setattr(extraction,'run_process',lambda *a,**kw:pytest.fail('Duration limit was bypassed via fallback'))
    with pytest.raises(MediaTooLong):media_url('https://www.douyin.com/video/123',tmp_path,lambda:False,lambda _:None)
    with pytest.raises(MediaTooLong):worker.add_vision({'source':{'kind':'url','content':'https://www.douyin.com/video/123'}},tmp_path,lambda:False,lambda _:None)

def test_public_douyin_rejects_before_media_download(tmp_path,monkeypatch):
    vid='123';requests=[]
    item={'aweme_id':vid,'desc':'长视频','video':{'duration':36000001,'play_addr':{'url_list':['https://cdn.example.com/video.mp4']}}}
    html='window._ROUTER_DATA = '+json.dumps({'item':item})
    original=httpx.Client
    def handler(request):
        requests.append(request)
        assert request.url.host != 'cdn.example.com'
        return httpx.Response(200,text=html)
    monkeypatch.setattr(douyin.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(douyin,'check_url',lambda url:url)
    with pytest.raises(MediaTooLong):douyin.public_video('https://www.douyin.com/video/'+vid,tmp_path,lambda:False,lambda _:None)
    assert len(requests)==1

def test_import_text_above_old_million_character_limit(library):
    text='开头条件KEY0000：不应丢失。\n'+('长文中间的重要条件与限制。'*80000)+'\n结尾条件KEY9999：必须完整保留。'
    assert len(text)>1000000
    client=TestClient(app)
    result=client.post('/api/import',json={'kind':'text','content':text})
    assert result.status_code==200
    saved=store.get_note(result.json()['note']['id'])
    assert saved['source']['content']==text
    assert client.get('/api/notes').json()[0]['source']=={'kind':'text'}
    extracted=extract(saved,lambda:False,lambda _:None)
    assert extracted['segments'][0]['text'].startswith('开头条件KEY0000')
    assert extracted['segments'][-1]['text'].endswith('结尾条件KEY9999：必须完整保留。')
    assert all(len(s['text'])<=4500 for s in extracted['segments'])
    assert ''.join(s['text'] for s in extracted['segments'])==text

def digest(text,refs):
    return dict(title='归纳',subtitle='分层记录',overview=text,sections=[dict(title='条件',kind='concept',markdown=text,keypoints=['条件'],source_ids=refs)],limitations=[],conclusion='保留完整知识范围')

def test_long_text_context_covers_every_chunk_and_reuses_checkpoints(library,monkeypatch):
    segments=[{'id':f's{i+1}','location':f'段{i+1}','text':f'KEY{i:04} '+('材料内容'*1120)} for i in range(240)]
    seen=[];stages=[]
    def generate(prompt,schema,stop,**kwargs):
        seen.append(prompt)
        keys=list(dict.fromkeys(re.findall(r'KEY\d{4}',prompt)))
        refs=list(dict.fromkeys(re.findall(r'\bs(\d+)\b',prompt)))
        return digest(' '.join(keys)+' 说明'*250,['s'+v for v in refs])
    monkeypatch.setattr(worker,'generate',generate)
    note={'segments':segments}
    result=worker.context_for(note,library,lambda:False,stages.append)
    assert len(result)<40000 and any('第2层' in s for s in stages)
    assert all(f'KEY{i:04}' in result for i in range(240))
    first_calls=len(seen)
    assert worker.context_for(note,library,lambda:False,lambda _:None)==result
    assert len(seen)==first_calls

def make_wav(path,seconds):
    with wave.open(str(path),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000)
        wav.writeframes(b'\0\0'*(16000*seconds))

def test_segmented_transcription_resumes_and_preserves_timestamps(library,monkeypatch):
    path=library/'speech.wav';make_wav(path,5)
    assert probe_duration(path,lambda:False)==5
    monkeypatch.setattr(extraction,'TRANSCRIBE_CHUNK_SECONDS',2)
    real_process=extraction.run_process;parts=[]
    def process(args,**kwargs):
        if 'backend.transcribe' not in args:return real_process(args,**kwargs)
        out=Path(args[-1]);parts.append(out.name)
        out.write_text(json.dumps([{'start':0,'end':1,'text':'这一段有效语音，保留时间位置。'}]))
        return b''
    monkeypatch.setattr(extraction,'run_process',process)
    with pytest.raises(Cancelled):transcribe(path,library,lambda:len(parts)==1,lambda _:None)
    assert parts==['transcript-part-0.json'] and not (library/'transcript.json').exists()
    result=transcribe(path,library,lambda:False,lambda _:None)
    assert parts==['transcript-part-0.json','transcript-part-2.json','transcript-part-4.json']
    assert [s['start'] for s in result]==[0,2,4]
    assert [s['end'] for s in result]==[1,3,5]
    assert not list(library.glob('transcript-part-*.wav'))
    assert transcribe(path,library,lambda:False,lambda _:None)==result
    assert len(parts)==3

def test_local_files_do_not_have_link_duration_limit(library,monkeypatch):
    monkeypatch.setattr(extraction,'transcribe',lambda *args:[segment('本地文件独立处理，不按链接的600分钟限制拒绝。','语音',start=36001,end=36002)])
    assert extraction.extract_file(library/'local.mp4',library,lambda:False,lambda _:None)['segments'][0]['end']==36002

def test_file_import_has_no_total_count_cap_and_failure_is_independent(library):
    client=TestClient(app);ids=[]
    for index in range(1001):
        response=client.post('/api/import/file',files={'file':(f'材料{index}.txt',f'第{index}份学习材料，保留独立的原文和处理任务。'.encode())})
        assert response.status_code==200
        ids.append(response.json()['note']['id'])
    assert len(set(ids))==1001
    assert client.post('/api/import/file',files={'file':('损坏空材料.pdf',b'')}).status_code==422
    for ext in ('.pdf','.pptx','.mp4','.mp3'):
        response=client.post('/api/import/file',files={'file':('材料'+ext,b'file-content-for-upload')})
        assert response.status_code==200 and response.json()['job']['status']=='queued'
        assert client.get('/api/notes/'+response.json()['note']['id']+'/source').content==b'file-content-for-upload'
    assert len(client.get('/api/notes').json())==1005
