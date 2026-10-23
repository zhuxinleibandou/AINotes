import asyncio
import base64
import json
import re
import stat
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from backend import generation, store, worker, extract
from backend.app import app
from backend.codex import Cancelled, GenerationError
from backend.models import ModelProfile, SettingsRequest, Note, VisualFrame

KEY='TEST_KEY_NOT_A_REAL_CREDENTIAL'

@pytest.fixture
def db(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.setattr(store,'DB',tmp_path/'library.sqlite3')
    store.init();worker.shutdown.clear()
    monkeypatch.setattr(extract,'check_url',lambda url:url)
    return tmp_path

def profile(provider='deepseek',**changes):
    return ModelProfile(**(generation.default_profile(provider)|changes))

def save(provider='deepseek',**changes):
    local=generation.PRESETS[provider]['local']
    generation.save_settings(SettingsRequest(whisper_model='mlx-community/whisper-large-v3-turbo',generation_backend='local' if local else 'api',api_provider=provider if not local else 'deepseek',local_provider=provider if local else 'ollama',providers={provider:profile(provider,**changes)}))

def transport(monkeypatch,handler):
    original=httpx.AsyncClient
    options=[]
    def client(**kwargs):
        options.append(kwargs)
        return original(transport=httpx.MockTransport(handler),**kwargs)
    monkeypatch.setattr(generation.httpx,'AsyncClient',client)
    return options

def reply(value,finish='stop'):
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value,ensure_ascii=False)},'finish_reason':finish}]})

def note():
    return dict(title='模型服务验收',subtitle='来源忠实',overview='保留材料条件和局限。',sections=[dict(title='要点',kind='concept',markdown='只整理提供的原文，不补充外部数据。',keypoints=['保留原文'],source_ids=['s1'])],limitations=['测试材料'],conclusion='完整保存有效结果。')

def test_old_settings_are_preserved_and_all_public_profiles_can_be_saved(db):
    settings=generation.public_settings()
    assert settings['generation_backend']=='codex'
    profiles={k:ModelProfile(**{field:value for field,value in p.items() if field!='api_key_configured'}) for k,p in settings['providers'].items()}
    generation.save_settings(SettingsRequest(whisper_model=settings['whisper_model'],providers=profiles))
    save(api_key=KEY)
    generation.save_settings(SettingsRequest(whisper_model='mlx-community/whisper-small-mlx'))
    assert store.settings()['generation_backend']=='api'
    assert generation.snapshot()['key']==KEY
    assert store.settings()['whisper_model'].endswith('small-mlx')

def test_secrets_not_in_settings_responses_or_database_and_blank_keeps_key(db):
    save(api_key=KEY)
    path=db/'secrets/model-deepseek.json'
    assert stat.S_IMODE(path.stat().st_mode)==0o600
    assert stat.S_IMODE(path.parent.stat().st_mode)==0o700
    assert KEY not in json.dumps(store.settings())
    assert KEY not in TestClient(app).get('/api/settings').text
    assert generation.public_settings()['providers']['deepseek']['api_key_configured']
    save(api_key='')
    assert generation.snapshot()['key']==KEY
    save(clear_api_key=True)
    assert not path.exists()
    assert not generation.public_settings()['providers']['deepseek']['api_key_configured']

def test_keys_bound_to_provider_and_endpoint(db):
    save(api_key=KEY)
    with pytest.raises(ValueError,match='API Key'):save('glm')
    with pytest.raises(ValueError,match='API Key'):save(base_url='https://other.example.test/v1')
    assert generation.snapshot()['key']==KEY
    assert generation.snapshot()['base_url']=='https://api.deepseek.com'

@pytest.mark.parametrize('url,local',[
    ('http://api.example.com/v1',False),('https://user:password@api.example.com/v1',False),
    ('https://127.0.0.1/v1',False),('https://192.168.1.1/v1',False),('https://example.com/v1?key=secret',False),
    ('https://example.com/v1#fragment',False),('https://example.com/v1/chat/completions',False),
    ('http://remote.example.com:11434/v1',True),('http://192.168.1.1/v1',True),('http://127.0.0.1:0/v1',True),
])
def test_endpoint_separation(url,local):
    with pytest.raises(ValueError):generation.endpoint(url,local)

@pytest.mark.parametrize('url',['http://localhost:11434/v1','http://127.0.0.1:1234/v1','http://[::1]:8080/v1'])
def test_loopback_endpoints_allowed(url):assert generation.endpoint(url,True)==url

def test_validation_errors_do_not_echo_keys(db):
    payload={'whisper_model':'mlx-community/whisper-large-v3-turbo','providers':{'deepseek':{'base_url':'https://api.deepseek.com','api_key':KEY*500,'max_tokens':-3}}}
    response=TestClient(app).put('/api/settings',json=payload)
    assert response.status_code==422 and KEY not in response.text

@pytest.mark.parametrize('provider',['deepseek','moonshot','kimi_code','glm'])
def test_official_cloud_presets_use_real_protocol_and_separate_keys(db,monkeypatch,provider):
    save(provider,api_key=KEY)
    requests=[]
    def handler(request):
        requests.append(request)
        assert request.url==generation.PRESETS[provider]['base_url']+'/chat/completions'
        assert request.headers['authorization']=='Bearer '+KEY
        assert request.headers['user-agent'].startswith('shiye-local/')
        payload=json.loads(request.content)
        assert payload['model']==generation.PRESETS[provider]['model']
        assert payload['response_format']=={'type':'json_object'}
        assert 'JSON Schema' in payload['messages'][0]['content']
        return reply(note())
    transport(monkeypatch,handler)
    assert generation.generate('只整理用户材料。',Note,lambda:False)['title']=='模型服务验收'
    assert len(requests)==1

def test_local_model_list_and_generation_skip_proxy_and_codex(db,monkeypatch):
    save('ollama',model='local-test-model')
    monkeypatch.setattr(generation.codex,'generate',lambda *a,**kw:pytest.fail('Local request reached Codex'))
    def handler(request):
        assert request.url.host=='127.0.0.1' and 'authorization' not in request.headers
        if request.method=='GET':return httpx.Response(200,json={'data':[{'id':'local-test-model'},{'id':'second-model'}]})
        return reply(note())
    options=transport(monkeypatch,handler)
    assert generation.models('ollama',profile('ollama'))==['local-test-model','second-model']
    assert generation.generate('本机材料。',Note,lambda:False)['title']=='模型服务验收'
    assert all(o['trust_env'] is False and o['follow_redirects'] is False for o in options)

def test_json_mode_unsupported_retries_same_service_only(db,monkeypatch):
    save('ollama',model='local-test-model');requests=[]
    def handler(request):
        payload=json.loads(request.content);requests.append(payload)
        if len(requests)==1:return httpx.Response(400,json={'error':{'message':'response_format not supported'}})
        assert 'response_format' not in payload
        return reply(note())
    transport(monkeypatch,handler)
    assert generation.generate('材料',Note,lambda:False)
    assert len(requests)==2

@pytest.mark.parametrize('status',[301,401,403,404,429,500])
def test_service_errors_are_useful_but_never_reflect_secrets(db,monkeypatch,status):
    save(api_key=KEY)
    transport(monkeypatch,lambda r:httpx.Response(status,json={'error':{'message':KEY}},headers={'location':'https://other.example.com'}))
    with pytest.raises(GenerationError) as exc:generation.generate('用户材料',Note,lambda:False)
    assert KEY not in str(exc.value)

@pytest.mark.parametrize('bad',[{}, {'choices':[]}, {'choices':[{'message':{'content':'not JSON'}}]}])
def test_invalid_responses_not_marked_complete(db,monkeypatch,bad):
    save('ollama',model='local-test-model')
    transport(monkeypatch,lambda r:httpx.Response(200,json=bad))
    item=store.create_note({'kind':'text','content':'这是用于验证无效输出的材料，结果不可被伪装成成功。'},'无效结果')
    job=store.create_job(item['id'],'summary');worker.process(job)
    assert store.get_job(job['id'])['status']=='failed'
    saved=store.get_note(item['id']);assert saved['segments'] and saved['note'] is None

def test_length_limit_is_explicit_failure(db,monkeypatch):
    save('ollama',model='local-test-model')
    transport(monkeypatch,lambda r:reply(note(),'length'))
    with pytest.raises(GenerationError,match='长度上限'):generation.generate('材料',Note,lambda:False)

def test_inflight_cancel_closes_http_request(db,monkeypatch):
    save('ollama',model='local-test-model');cancelled=[]
    async def handler(request):
        try:await asyncio.sleep(10)
        finally:cancelled.append(True)
        return reply(note())
    transport(monkeypatch,handler)
    started=time.monotonic()
    with pytest.raises(Cancelled):generation.generate('材料',Note,lambda:time.monotonic()-started>.03)
    assert time.monotonic()-started<2 and cancelled

def test_running_job_keeps_local_snapshot_after_settings_switch(db,monkeypatch):
    save(api_key=KEY);save('ollama',model='local-test-model');requests=[]
    def handler(request):
        requests.append(request)
        assert request.url.host=='127.0.0.1'
        payload=json.loads(request.content)
        if len(requests)==1:
            store.save_settings(store.settings()|{'generation_backend':'api'})
            return reply(note())
        assert 'chapters' in payload['messages'][0]['content']
        return reply({'title':'本地课程','description':'概念先行','chapters':[{'id':'c1','title':'概念','objective':'理解','source_ids':['s1']}]})
    transport(monkeypatch,handler)
    item=store.create_note({'kind':'text','content':'原文只讨论材料归纳与学习路径，课程按知识顺序推进。'},'快照验证',mode='course')
    job=store.create_job(item['id'],'summary');worker.process(job)
    assert store.get_job(job['id'])['status']=='completed' and len(requests)==2
    assert store.get_note(item['id'])['artifacts']['course']['title']=='本地课程'
    assert generation.CURRENT.get() is None
    assert generation.snapshot()['backend']=='api'

def test_image_capability_and_payload(db,monkeypatch):
    save('ollama',model='vision-test')
    image=db/'frame.jpg';image.write_bytes(b'test-image')
    with pytest.raises(GenerationError,match='图片输入'):generation.generate('观察画面',VisualFrame,lambda:False,images=[image])
    save('ollama',model='vision-test',supports_images=True)
    def handler(request):
        content=json.loads(request.content)['messages'][1]['content']
        assert content[1]['image_url']['url']=='data:image/jpeg;base64,'+base64.b64encode(b'test-image').decode()
        return reply({'description':'只描述画面','visible_text':'TEST','caveats':'验收返回'})
    transport(monkeypatch,handler)
    assert generation.generate('观察画面',VisualFrame,lambda:False,images=[image])['visible_text']=='TEST'

def test_model_endpoints_test_unsaved_profile_without_storing_credentials(db,monkeypatch):
    transport(monkeypatch,lambda r:reply({'ok':True}) if r.method=='POST' else httpx.Response(200,json={'data':[{'id':'test-model'}]}))
    client=TestClient(app)
    payload={'provider':'deepseek','profile':generation.default_profile('deepseek')|{'api_key':KEY}}
    response=client.post('/api/settings/test-model',json=payload)
    assert response.status_code==200 and response.json()['ok']
    assert KEY not in response.text
    assert client.post('/api/settings/models',json=payload).json()['models']==['test-model']
    assert not (db/'secrets/model-deepseek.json').exists()

def test_different_models_do_not_reuse_compaction_cache(db):
    save('ollama',model='model-one');first=generation.fingerprint()
    save('ollama',model='model-two');assert generation.fingerprint()!=first
    assert generation.context_chars()==12000

def test_model_switch_waits_for_all_queued_tasks_to_pause(db):
    client=TestClient(app)
    item=store.create_note({'kind':'text','content':'任务暂停之前不允许切换模型，排队任务也必须暂停。'},'排队任务')
    job=store.create_job(item['id'],'summary',{'preserve':'yes'})
    payload={'whisper_model':'mlx-community/whisper-large-v3-turbo','generation_backend':'api','api_provider':'deepseek','providers':{'deepseek':generation.default_profile('deepseek')|{'api_key':KEY}}}
    response=client.put('/api/settings',json=payload)
    assert response.status_code==409 and '暂停' in response.text
    assert not (db/'secrets/model-deepseek.json').exists()
    assert generation.public_settings()['generation_backend']=='codex'
    assert client.post('/api/settings/pause-tasks').json()['active_tasks']==[]
    assert store.get_job(job['id'])['status']=='paused'
    assert client.put('/api/settings',json=payload).status_code==200
    assert generation.snapshot()['backend']=='api'
    assert client.post('/api/settings/resume-tasks').json()['resumed']==1
    assert store.get_job(job['id'])['status']=='queued'
    assert store.get_job(job['id'])['args']=={'preserve':'yes'}
    assert client.put('/api/settings',json=payload).status_code==409

@pytest.mark.parametrize('action,waiting,settled',[('pause-tasks','pausing','paused'),('cancel','cancelling','cancelled')])
def test_switch_remains_locked_until_inflight_request_is_closed(db,monkeypatch,action,waiting,settled):
    import threading
    save('ollama',model='local-test-model')
    entered=threading.Event();closing=threading.Event();allow_close=threading.Event()
    async def handler(request):
        entered.set()
        try: await asyncio.sleep(10)
        finally:
            closing.set()
            await asyncio.to_thread(allow_close.wait,3)
        return reply(note())
    transport(monkeypatch,handler)
    item=store.create_note({'kind':'text','content':'只有后台请求真正停止后，才能切换模型。保留已经完成的原文解析。'},'停止确认')
    job=store.create_job(item['id'],'summary')
    thread=threading.Thread(target=worker.process,args=(job,));thread.start()
    try:
        assert entered.wait(3)
        client=TestClient(app)
        if action=='cancel':client.post('/api/jobs/'+job['id']+'/cancel')
        else:client.post('/api/settings/'+action)
        assert closing.wait(3)
        assert store.get_job(job['id'])['status']==waiting
        assert client.put('/api/settings',json={'whisper_model':'mlx-community/whisper-large-v3-turbo','generation_backend':'codex'}).status_code==409
        assert client.post('/api/settings/clear-cache').status_code==409
    finally:
        allow_close.set();thread.join(5)
    assert not thread.is_alive()
    assert store.get_job(job['id'])['status']==settled
    assert store.get_note(item['id'])['segments']
    assert client.get('/api/settings/tasks').json()['active_tasks']==[]
    assert client.put('/api/settings',json={'whisper_model':'mlx-community/whisper-large-v3-turbo','generation_backend':'codex'}).status_code==200

def test_pause_at_final_completion_never_leaves_phantom_running_task(db,monkeypatch):
    save('ollama',model='local-test-model')
    transport(monkeypatch,lambda r:reply(note()))
    complete=store.complete_job
    def pause_then_complete(ident):
        store.pause_tasks();complete(ident)
    monkeypatch.setattr(store,'complete_job',pause_then_complete)
    item=store.create_note({'kind':'text','content':'完成结果保存之后发生暂停，后台也必须确认处理结束。'},'完成时暂停')
    job=store.create_job(item['id'],'summary');worker.process(job)
    assert store.get_note(item['id'])['note']
    assert store.get_job(job['id'])['status']=='paused'
    assert not store.active_tasks()
    save('ollama',model='another-model')

def test_restart_settles_stop_requests_and_retry_does_not_duplicate_paused_job(db):
    client=TestClient(app)
    ids=[]
    for status in ('pausing','cancelling','running'):
        item=store.create_note({'kind':'text','content':'重启恢复已暂停的任务状态，避免永远占用模型切换。'},status)
        job=store.create_job(item['id'],'summary');store.set_job(job['id'],status=status);ids.append(job['id'])
    store.init()
    assert [store.get_job(i)['status'] for i in ids]==['paused','cancelled','interrupted']
    assert not store.active_tasks()
    retried=client.post('/api/jobs/'+ids[0]+'/retry')
    assert retried.status_code==200
    assert store.paused_tasks()==[]
    assert client.post('/api/settings/resume-tasks').json()['resumed']==0
    assert len(store.active_tasks())==1
