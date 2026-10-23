"""Selectable generation service. Secrets stay local and are never returned to the browser."""
import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import re
import time
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel
from . import codex, store
from .codex import Cancelled, GenerationError

PRESETS = {
    'deepseek': dict(label='DeepSeek', local=False, base_url='https://api.deepseek.com', model='deepseek-flash', models=['deepseek-flash','deepseek-v4-pro'], docs='https://api-docs.deepseek.com/'),
    'moonshot': dict(label='Kimi 开放平台', local=False, base_url='https://api.moonshot.cn/v1', model='kimi-k3', models=['kimi-k3','kimi-k2.5'], docs='https://www.kimi.com/en/help/kimi-api/api-overview'),
    'kimi_code': dict(label='Kimi Code', local=False, base_url='https://api.kimi.com/coding/v1', model='kimi-for-coding', models=['kimi-for-coding','k3','k3-256k','kimi-for-coding-highspeed'], docs='https://www.kimi.com/code/docs/'),
    'glm': dict(label='GLM · 智谱', local=False, base_url='https://open.bigmodel.cn/api/paas/v4', model='glm-5.3', models=['glm-5.3','glm-5.3-flash'], docs='https://docs.bigmodel.cn/api-reference/模型-api/对话补全'),
    'custom': dict(label='其他兼容 API', local=False, base_url='', model='', models=[], docs=''),
    'ollama': dict(label='Ollama', local=True, base_url='http://127.0.0.1:11434/v1', model='', models=[], docs='https://docs.ollama.com/api/openai-compatibility'),
    'lmstudio': dict(label='LM Studio', local=True, base_url='http://127.0.0.1:1234/v1', model='', models=[], docs='https://lmstudio.ai/docs/developer/openai-compat'),
    'local_custom': dict(label='其他本机服务', local=True, base_url='http://127.0.0.1:8080/v1', model='', models=[], docs=''),
}
CURRENT = ContextVar('shiye_generation',default=None)

def default_profile(provider):
    preset = PRESETS[provider]
    return dict(base_url=preset['base_url'],model=preset['model'],supports_images=False,
                output_format='json_object',max_tokens=4096 if preset['local'] else 8192,
                context_chars=12000 if preset['local'] else 40000,reasoning_effort='default')

def endpoint(value, local):
    value = value.strip().rstrip('/')
    try:
        p = urlparse(value)
        port = p.port
        if not p.hostname or p.username or p.password or p.query or p.fragment or port == 0:
            raise ValueError()
        host = p.hostname.lower()
        loopback = host in ('localhost','127.0.0.1','::1')
        if local:
            if not loopback or p.scheme not in ('http','https'):
                raise ValueError('本地模型地址必须指向本机 localhost、127.0.0.1 或 ::1。')
        else:
            if p.scheme != 'https' or loopback or host.endswith('.local'):
                raise ValueError('模型API请使用公开HTTPS地址；本机服务请选择“本地模型”。')
            try: address = ipaddress.ip_address(host)
            except ValueError: address = None
            if address is not None and not address.is_global:
                raise ValueError('模型API不能指向局域网或保留地址。')
        if p.path.endswith(('/chat/completions','/models')):
            raise ValueError('请填写服务的Base URL，不含 /chat/completions 或 /models。')
    except ValueError as exc:
        raise ValueError(str(exc) if str(exc) and 'port' not in str(exc).lower() else '模型服务地址格式无效。') from None
    return value

def read_key(provider, base_url):
    path = store.DATA/'secrets'/('model-'+provider+'.json')
    if not path.is_file(): return ''
    value = json.loads(path.read_text())
    return value.get('key','') if value.get('base_url') == base_url else ''

def public_settings():
    settings = store.settings()
    profiles = {}
    for provider in PRESETS:
        profile = default_profile(provider) | settings.get('providers',{}).get(provider,{})
        profiles[provider] = profile | {'api_key_configured':bool(read_key(provider,profile['base_url']))}
    return settings | dict(generation_backend=settings.get('generation_backend','codex'),
                           api_provider=settings.get('api_provider','deepseek'),local_provider=settings.get('local_provider','ollama'),
                           providers=profiles,provider_presets=PRESETS,active_tasks=store.active_tasks(),paused_tasks=len(store.paused_tasks()))

def resolved_profile(provider, draft=None):
    if provider not in PRESETS: raise ValueError('模型服务无效。')
    profile = default_profile(provider) | store.settings().get('providers',{}).get(provider,{})
    if draft is not None:
        incoming = draft.model_dump(exclude={'api_key','clear_api_key'})
        profile.update(incoming)
    profile['base_url'] = endpoint(profile['base_url'],PRESETS[provider]['local'])
    key = read_key(provider,profile['base_url'])
    if draft is not None:
        if draft.clear_api_key: key = ''
        if draft.api_key and draft.api_key.get_secret_value().strip(): key = draft.api_key.get_secret_value().strip()
    return profile | {'provider':provider,'key':key,'backend':'local' if PRESETS[provider]['local'] else 'api'}

def save_settings(request):
    # Claiming a job, creating new work, and changing model settings share the same SQLite write lock.
    with store.connection() as con:
        con.execute('BEGIN IMMEDIATE')
        if con.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running','pausing','cancelling') LIMIT 1").fetchone():
            raise ValueError('请先暂停当前任务，等待处理完全停止后，再保存或切换模型。')
        _save_settings(request,con)

def _save_settings(request,con):
    current = store.settings()
    fields = request.model_dump(exclude={'providers'},exclude_unset=True)
    pending = {}
    profiles = dict(current.get('providers',{}))
    for provider,draft in (request.providers or {}).items():
        if not draft.base_url.strip() and not draft.model.strip() and not draft.api_key and not draft.clear_api_key:
            continue
        profile = resolved_profile(provider,draft)
        pending[provider] = profile
        profiles[provider] = {k:v for k,v in profile.items() if k not in ('key','provider','backend')}
    updated = current | fields | {'providers':profiles}
    backend = updated.get('generation_backend','codex')
    selected = updated.get('local_provider','ollama') if backend == 'local' else updated.get('api_provider','deepseek')
    if backend != 'codex':
        profile = pending.get(selected) or resolved_profile(selected)
        if not profile['model'].strip(): raise ValueError('请填写模型ID，或先读取服务中的模型列表。')
        clearing = bool(request.providers and selected in request.providers and request.providers[selected].clear_api_key)
        if backend == 'api' and not profile['key'] and not clearing: raise ValueError('请填写这个服务的API Key；更换服务地址后需要重新填写密钥。')
    # Validate the whole change before touching any secret file.
    folder = store.DATA/'secrets'
    folder.mkdir(mode=0o700,exist_ok=True);folder.chmod(0o700)
    for provider,profile in pending.items():
        path = folder/('model-'+provider+'.json')
        if not profile['key']:
            path.unlink(missing_ok=True)
            continue
        temp = path.with_suffix('.tmp')
        fd = os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump({'base_url':profile['base_url'],'key':profile['key']},stream)
        temp.replace(path)
    con.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(json.dumps(updated),))

def snapshot():
    settings = store.settings()
    backend = settings.get('generation_backend','codex')
    if backend == 'codex': return {'backend':'codex','model':settings.get('model','')}
    provider = settings.get('local_provider','ollama') if backend == 'local' else settings.get('api_provider','deepseek')
    return resolved_profile(provider)

def active_config():
    return CURRENT.get() or snapshot()

def context_chars():
    profile = active_config()
    return profile.get('context_chars',40000)

def fingerprint():
    profile = active_config()
    return hashlib.sha256(json.dumps({k:v for k,v in profile.items() if k != 'key'},sort_keys=True).encode()).hexdigest()[:12]

async def request_json(profile, method, path, payload=None):
    if profile['backend'] == 'api':
        # DNS and reserved-address checks are also performed immediately before sending credentials.
        from .extract import check_url, ExtractionError
        parsed = urlparse(profile['base_url'])
        try: check_url('https://'+parsed.hostname)
        except ExtractionError:
            raise GenerationError('无法访问模型API地址，请检查网络与地址。') from None
    headers = {'User-Agent':'shiye-local/0.1.0','Accept':'application/json'}
    if profile['key']: headers['Authorization'] = 'Bearer '+profile['key']
    async with httpx.AsyncClient(timeout=httpx.Timeout(900,connect=10),follow_redirects=False,trust_env=profile['backend']!='local') as client:
        async with client.stream(method,profile['base_url']+path,headers=headers,json=payload) as response:
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw)>8_000_000: raise GenerationError('模型返回内容过大，请减少输出长度后重试。')
            try: body = json.loads(raw)
            except ValueError: body = None
            if response.status_code >= 300:
                # Do not reflect vendor error text: it can contain keys or submitted material.
                status = response.status_code
                if status == 400 and 'response_format' in json.dumps(body).lower():
                    return {'_unsupported_format':True}
                messages = {401:'密钥无效或账号没有所选模型权限。',403:'服务拒绝访问，请检查密钥、模型权限及服务的适用范围。',404:'未找到模型或接口，请检查模型ID和Base URL。',429:'服务额度不足或请求过于频繁，请稍后重试。'}
                raise GenerationError(messages.get(status,f'模型服务返回错误（HTTP {status}），请检查配置后重试。'))
            if not isinstance(body,dict): raise GenerationError('模型服务没有返回有效JSON数据，请检查接口地址。')
            return body

async def controlled(coro, stop):
    task = asyncio.create_task(coro)
    started = time.monotonic()
    try:
        while not task.done():
            if stop(): raise Cancelled()
            if time.monotonic()-started>900: raise GenerationError('模型请求超时，材料和已完成步骤已保留。')
            await asyncio.wait({task},timeout=.2)
        if stop(): raise Cancelled()
        return await task
    except httpx.TimeoutException:
        raise GenerationError('模型服务连接超时，请检查服务是否运行及网络。') from None
    except httpx.HTTPError:
        raise GenerationError('无法连接模型服务，请检查服务地址、网络或本地模型是否已启动。') from None
    finally:
        if not task.done(): task.cancel()
        await asyncio.gather(task,return_exceptions=True)

def api_generate(prompt, schema, stop, profile, images=None):
    if not profile['model'].strip(): raise GenerationError('尚未选择模型，请到设置页填写模型ID。')
    if profile['backend']=='api' and not profile['key']: raise GenerationError('尚未配置API Key，请到设置页保存密钥。')
    if images and not profile['supports_images']: raise GenerationError('当前模型未启用图片输入，请在设置中选择视觉模型并启用图片支持。')
    instruction = '只输出一个JSON对象，不要Markdown围栏或推理过程。严格遵守以下JSON Schema，所有必填字段必须完整：\n'+json.dumps(schema.model_json_schema(),ensure_ascii=False)
    content = prompt
    if images:
        content = [{'type':'text','text':prompt}] + [{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(Path(path).read_bytes()).decode()}} for path in images]
    payload = {'model':profile['model'],'messages':[{'role':'system','content':instruction},{'role':'user','content':content}],
               'stream':False,'max_tokens':profile['max_tokens']}
    if profile['reasoning_effort']!='default': payload['reasoning_effort'] = profile['reasoning_effort']
    output = profile['output_format']
    if output=='json_schema':payload['response_format']={'type':'json_schema','json_schema':{'name':'learning_content','strict':True,'schema':schema.model_json_schema()}}
    elif output=='json_object':payload['response_format']={'type':'json_object'}
    async def complete():
        result = await request_json(profile,'POST','/chat/completions',payload)
        if result.get('_unsupported_format') and 'response_format' in payload:
            payload.pop('response_format')
            result = await request_json(profile,'POST','/chat/completions',payload)
        try:
            choice = result['choices'][0]
            if choice.get('finish_reason') in ('length','max_tokens'):
                raise GenerationError('模型输出达到长度上限，未保存不完整结果。请在设置中增加输出上限后重试。')
            text = choice['message']['content']
            if not isinstance(text,str): raise ValueError()
            text = re.sub(r'^\s*<think>.*?</think>\s*','',text,flags=re.S)
            text = re.sub(r'^\s*```(?:json)?\s*\n?|\n?```\s*$','',text).strip()
            return schema.model_validate_json(text).model_dump()
        except (KeyError,IndexError,TypeError,ValueError):
            raise GenerationError('模型输出未通过内容格式检查，未保存为成功结果。可以重试或更换模型。') from None
    return asyncio.run(controlled(complete(),stop))

def generate(prompt: str, schema: type[BaseModel], stop, model='', images=None):
    profile = active_config()
    if profile['backend']=='codex':
        return codex.generate(prompt,schema,stop,model=profile.get('model') or model,images=images)
    return api_generate(prompt,schema,stop,profile,images)

def models(provider,draft):
    profile = resolved_profile(provider,draft)
    if profile['backend']=='api' and not profile['key']: raise GenerationError('请先填写API Key。')
    result = asyncio.run(controlled(request_json(profile,'GET','/models'),lambda:False))
    return sorted({m['id'] for m in result.get('data',[]) if isinstance(m,dict) and isinstance(m.get('id'),str)})
