import asyncio
import json
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import store, worker, generation
from .version import VERSION
from .codex import executable, config
from .extract import ALLOWED, normalize_url
from .models import ImportRequest, GenerateRequest, EditRequest, ProgressRequest, SettingsRequest, ModelConnectionRequest

@asynccontextmanager
async def lifespan(app):
    with store.instance_lock():
        store.init()
        worker.shutdown.clear()
        task = asyncio.create_task(worker.loop())
        try:
            yield
        finally:
            worker.shutdown.set()
            try:
                await asyncio.wait_for(asyncio.shield(task),timeout=8)
            except asyncio.TimeoutError:
                task.cancel()

app = FastAPI(title='拾页 · 本地学习', lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1','localhost','testserver'])

@app.middleware('http')
async def local_requests(request:Request, call_next):
    origin = request.headers.get('origin')
    if request.url.path.startswith('/api') and request.method not in ('GET','HEAD','OPTIONS') and origin:
        parsed = urlparse(origin)
        if parsed.hostname not in ('localhost','127.0.0.1') or parsed.scheme != 'http' or parsed.port not in (request.url.port,5173):
            return JSONResponse({'detail':'仅接受本机学习页面的请求。'},status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response

@app.exception_handler(KeyError)
async def missing(request,exc):
    return JSONResponse({'detail':'这份记录不存在。'},status_code=404)

@app.exception_handler(ValueError)
async def invalid(request,exc):
    return JSONResponse({'detail':str(exc)},status_code=409)

@app.exception_handler(RequestValidationError)
async def invalid_request(request,exc):
    if request.url.path.startswith('/api/settings'):
        return JSONResponse({'detail':'模型设置格式无效，请检查地址、模型ID与数值范围。'},status_code=422)
    from fastapi.exception_handlers import request_validation_exception_handler
    return await request_validation_exception_handler(request,exc)

def public_note(note):
    source = note['source'].copy()
    return {**note,'source':source,'job':store.latest_job(note['id'])}

@app.get('/api/health')
def health():
    return {'ok':True,'name':'拾页','version':VERSION,'installation':__import__('hashlib').sha256(str(store.ROOT).encode()).hexdigest()[:16]}

@app.get('/api/settings')
def settings():
    available,logged,model = False,False,''
    try:
        command = executable()
        available = True
        result = subprocess.run([command,'login','status'],capture_output=True,timeout=8)
        logged = result.returncode == 0
        model = config().get('model','Codex 默认模型')
    except (OSError,RuntimeError,subprocess.TimeoutExpired):
        pass
    disk = shutil.disk_usage(store.DATA)
    return generation.public_settings() | {'codex_available':available,'codex_logged_in':logged,'default_model':model,
           'storage':str(store.DATA),'free_gb':round(disk.free/1024**3,1),'ffmpeg':bool(shutil.which('ffmpeg')),
           'ocr':bool(shutil.which('swiftc')),'transcription':'MLX Whisper · 本机处理',
           'upload_limit_mb':500,'platform_cookies':{name:(store.DATA/'secrets'/(name+'-cookies.txt')).is_file() for name in ('douyin','bilibili','youtube')}}

@app.put('/api/settings')
def update_settings(request:SettingsRequest):
    generation.save_settings(request)
    return {'ok':True}

@app.post('/api/settings/pause-tasks')
def pause_model_tasks():
    store.pause_tasks()
    return {'ok':True,'active_tasks':store.active_tasks(),'paused_tasks':len(store.paused_tasks())}

@app.get('/api/settings/tasks')
def model_tasks():
    return {'active_tasks':store.active_tasks(),'paused_tasks':len(store.paused_tasks())}

@app.post('/api/settings/resume-tasks')
def resume_model_tasks():
    return {'ok':True,'resumed':store.resume_tasks()}

@app.post('/api/settings/models')
def model_list(request:ModelConnectionRequest):
    try:
        return {'models':generation.models(request.provider,request.profile)}
    except (generation.GenerationError,ValueError) as exc:
        raise HTTPException(422,str(exc)) from None

@app.post('/api/settings/test-model')
def test_model(request:ModelConnectionRequest):
    from pydantic import BaseModel
    from typing import Literal
    class ConnectionResult(BaseModel):
        ok: Literal[True]
    try:
        profile = generation.resolved_profile(request.provider,request.profile)
        profile['max_tokens'] = min(profile['max_tokens'],2048)
        generation.api_generate('这是连接测试，不含用户材料。请返回JSON对象：{"ok":true}',ConnectionResult,lambda:False,profile)
        return {'ok':True,'message':'已完成一次实际生成，结构化结果检查通过。'}
    except (generation.GenerationError,ValueError) as exc:
        raise HTTPException(422,str(exc)) from None

@app.post('/api/settings/platform-cookies')
async def platform_cookies(platform:str=Form(...),file:UploadFile=File(...)):
    domains={'douyin':('douyin.com','iesdouyin.com'),'bilibili':('bilibili.com','b23.tv'),'youtube':('youtube.com','google.com','youtu.be')}
    if platform not in domains: raise HTTPException(422,'平台无效。')
    data=await file.read(1024*1024+1)
    await file.close()
    if len(data)>1024*1024: raise HTTPException(413,'Cookie 文件过大。')
    try: text=data.decode('utf-8-sig')
    except UnicodeError: raise HTTPException(422,'请选择 Netscape 格式的 UTF-8 Cookie 文件。')
    lines=['# Netscape HTTP Cookie File']
    for line in text.splitlines():
        if not line.strip() or (line.startswith('#') and not line.startswith('#HttpOnly_')):continue
        cells=line.split('\t')
        if len(cells)!=7: raise HTTPException(422,'Cookie 格式不正确，需要 Netscape cookies.txt 格式。')
        domain=cells[0].removeprefix('#HttpOnly_').lstrip('.')
        if any(domain==d or domain.endswith('.'+d) for d in domains[platform]):lines.append(line)
    if len(lines)==1:raise HTTPException(422,'文件中没有这个平台的 Cookie。')
    folder=store.DATA/'secrets';folder.mkdir(mode=0o700,exist_ok=True)
    path=folder/(platform+'-cookies.txt');path.write_text('\n'.join(lines)+'\n');path.chmod(0o600)
    return {'ok':True}

@app.post('/api/settings/platform-cookies/{platform}/remove')
def remove_cookies(platform:str):
    if platform not in ('douyin','bilibili','youtube'):raise HTTPException(422,'平台无效。')
    (store.DATA/'secrets'/(platform+'-cookies.txt')).unlink(missing_ok=True)
    return {'ok':True}

@app.post('/api/settings/clear-cache')
def clear_cache():
    # Only disposable compiler and compression caches; originals, exports and library are retained.
    if store.active_tasks():
        raise HTTPException(409,'请在任务处理结束后清理缓存。')
    removed = 0
    for path in list((store.DATA/'materials').glob('*/chunk-*.json')) + list((store.DATA/'cache').glob('*')):
        if path.is_file():
            removed += path.stat().st_size
            path.unlink()
    return {'ok':True,'freed_bytes':removed}

@app.get('/api/notes')
def notes(q:str=''):
    return store.list_notes(q[:200])

@app.post('/api/import')
def import_text(request:ImportRequest):
    content = request.content.strip()
    if request.kind == 'text' and len(content)<15:
        raise HTTPException(422,'请提供至少15字的正文，便于生成有依据的笔记。')
    if request.kind == 'url':
        try:
            normalized = normalize_url(content)
        except Exception as exc:
            raise HTTPException(422,str(exc)) from None
        title = request.title or '正在读取链接'
        source = {'kind':'url','content':normalized,'original':content}
    else:
        title = request.title or content.splitlines()[0].lstrip('# ')[:80]
        source = {'kind':'text','content':content}
    note = store.create_note(source,title,request.instructions,request.format,request.mode)
    job = store.create_job(note['id'],'summary')
    return {'note':public_note(note),'job':job}

@app.post('/api/import/file')
async def import_file(file:UploadFile=File(...), instructions:str=Form(''), format:str=Form('poster'), mode:str=Form('summary')):
    filename = Path(file.filename or '录音.webm').name
    if Path(filename).suffix.lower() not in ALLOWED:
        raise HTTPException(422,'不支持此格式。请上传 PDF、DOCX、PPTX、TXT、Markdown、图片或音视频；旧版 DOC/PPT 请先另存。')
    if format not in ('poster','markdown','mindmap') or mode not in ('summary','course'):
        raise HTTPException(422,'生成选项无效。')
    if len(instructions)>4000:
        raise HTTPException(422,'学习要求请控制在4000字以内。')
    # Stage before creating a library record so an oversized upload leaves no broken note.
    import tempfile
    staged = store.DATA/'uploads'
    staged.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=staged,delete=False) as f:
        temp = Path(f.name)
        size = 0
        try:
            while chunk := await file.read(1024*1024):
                size += len(chunk)
                if size > 500*1024*1024:
                    raise HTTPException(413,'文件超过500MB，请分段后上传。')
                f.write(chunk)
            if size == 0:
                raise HTTPException(422,'文件是空的，请重新选择。')
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        finally:
            await file.close()
    note = store.create_note({'kind':'file','filename':filename,'size':size},Path(filename).stem,instructions,format,mode)
    dest = store.DATA/'materials'/note['id']/'source'
    dest.mkdir(parents=True)
    shutil.move(temp,dest/filename)
    job = store.create_job(note['id'],'summary')
    return {'note':public_note(note),'job':job}

@app.get('/api/notes/{ident}')
def get_note(ident:str):
    return public_note(store.get_note(ident))

@app.post('/api/notes/{ident}/generate')
def generate_note(ident:str,request:GenerateRequest):
    note = store.get_note(ident)
    if request.kind not in ('summary','vision') and not note['note']:
        raise HTTPException(409,'请先完成笔记生成。')
    chapters = note['artifacts'].get('course',{}).get('chapters',[])
    if request.kind == 'lesson' and not any(c['id']==request.chapter_id for c in chapters):
        raise HTTPException(422,'请先生成课程目录并选择有效章节。')
    if request.kind == 'stage' and not 1 <= request.boundary <= len(chapters):
        raise HTTPException(422,'阶段测验范围无效。')
    return store.create_job(ident,request.kind,request.model_dump())

@app.put('/api/notes/{ident}')
def edit(ident:str,request:EditRequest):
    note = store.get_note(ident)
    from .codex import validate_refs
    try:
        validate_refs(request.note.model_dump(),{s['id'] for s in note['segments']})
    except Exception as exc:
        raise HTTPException(422,str(exc)) from None
    return public_note(store.save_note_version(ident,request.note.model_dump(),expected=request.revision))

@app.get('/api/notes/{ident}/versions')
def versions(ident:str):
    store.get_note(ident)
    with store.connection() as con:
        rows = con.execute('SELECT revision,created,body FROM versions WHERE note_id=? ORDER BY created DESC',(ident,)).fetchall()
    return [{'revision':r['revision'],'created':r['created'],'note':json.loads(r['body'])} for r in rows]

@app.get('/api/notes/{ident}/learning-history')
def learning_history(ident:str):
    store.get_note(ident)
    with store.connection() as con:
        rows=con.execute('SELECT * FROM artifact_history WHERE note_id=? ORDER BY created DESC',(ident,)).fetchall()
    return [{'id':r['id'],'key':r['artifact_key'],'revision':r['revision'],'created':r['created'],'content':json.loads(r['body']),'progress':json.loads(r['progress'])} for r in rows]

@app.put('/api/notes/{ident}/progress')
def progress(ident:str,request:ProgressRequest):
    return public_note(store.patch_progress(ident,request))

@app.get('/api/jobs/{ident}')
def get_job(ident:str):
    return store.get_job(ident)

@app.post('/api/jobs/{ident}/cancel')
def cancel(ident:str):
    store.get_job(ident)
    with store.connection() as con:
        con.execute("UPDATE jobs SET status='cancelling',stage='正在取消，等待当前处理停止',updated=? WHERE id=? AND status IN ('running','pausing')",(store.now(),ident))
        con.execute("UPDATE jobs SET status='cancelled',stage='已取消；已完成的解析步骤会保留',updated=? WHERE id=? AND status IN ('queued','paused')",(store.now(),ident))
    return store.get_job(ident)

@app.post('/api/jobs/{ident}/retry')
def retry(ident:str):
    job = store.get_job(ident)
    if job['status'] not in ('failed','cancelled','interrupted','paused'):
        raise HTTPException(409,'此任务不需要重试。')
    return store.create_job(job['note_id'],job['kind'],job['args'])

def markdown(note,kind):
    content = note['note']
    if content is None:
        raise HTTPException(409,'笔记尚未生成。')
    if kind == 'outline':
        sections = ['# '+content['title']]
        for section in content['sections']:
            sections.append('## '+section['title']+'\n'+'\n'.join('- '+k for k in section['keypoints']))
    elif kind == 'overview':
        sections = ['# '+content['title'],content['overview']]
    else:
        sections = ['# '+content['title'],'> '+content['subtitle'],'## 一页速览\n\n'+content['overview']]
        for section in content['sections']:
            sections.append('## '+section['title']+'\n\n'+section['markdown'])
        if content['limitations']:
            sections.append('## 限制与待确认\n\n'+'\n'.join('- '+x for x in content['limitations']))
        sections.append('## 一句话总结\n\n'+content['conclusion'])
    sections += ['---','处理范围：'+note['scope']]
    if note['source']['kind'] == 'url':
        sections.append('原始链接：'+note['source']['content'])
    else:
        sections.append('来源：'+note['source'].get('filename','粘贴正文'))
    return '\n\n'.join(sections)+'\n'

@app.get('/api/notes/{ident}/export/{kind}')
def export_markdown(ident:str,kind:str):
    if kind not in ('markdown','overview','outline'):
        raise HTTPException(404,'未知导出格式。')
    note = store.get_note(ident)
    body = markdown(note,kind)
    filename = note['title'].replace('/','-').replace('\\','-')[:100]+('-速览' if kind=='overview' else '-大纲' if kind=='outline' else '')+'.md'
    export_dir = store.DATA/'exports'/ident
    export_dir.mkdir(parents=True,exist_ok=True)
    (export_dir/f'r{note["revision"]}-{kind}.md').write_text(body)
    return Response(body,media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename)})

@app.post('/api/notes/{ident}/exports')
async def save_export(ident:str,file:UploadFile=File(...), revision:int=Form(...)):
    note = store.get_note(ident)
    if revision>note['revision'] or revision<1:
        raise HTTPException(422,'无效的导出版本。')
    name = Path(file.filename or 'export.png').name
    if Path(name).suffix.lower() not in ('.png','.svg','.zip'):
        raise HTTPException(422,'不支持的导出格式。')
    data = await file.read(64*1024*1024+1)
    await file.close()
    if len(data)>64*1024*1024:
        raise HTTPException(413,'导出文件过大。')
    folder = store.DATA/'exports'/ident
    folder.mkdir(parents=True,exist_ok=True)
    (folder/f'r{revision}-{store.uid()[:8]}-{name}').write_bytes(data)
    return {'ok':True}

@app.get('/api/notes/{ident}/source')
def source(ident:str):
    note = store.get_note(ident)
    if note['source']['kind']!='file':
        raise HTTPException(404,'此材料没有上传文件。')
    filename = Path(note['source']['filename']).name
    return FileResponse(store.DATA/'materials'/ident/'source'/filename,filename=filename)

frontend = store.ROOT/'frontend'/'dist'
if frontend.exists():
    app.mount('/',StaticFiles(directory=frontend,html=True),name='frontend')
