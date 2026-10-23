import asyncio
import hashlib
import httpx
import json
import re
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlparse
from . import store
from .codex import SYSTEM, Cancelled, validate_refs
from . import generation
from .generation import generate
from .extract import extract, segment, timestamp, finalize, ExtractionError, MediaTooLong, check_link_file
from .models import Note, Course, Lesson, Quiz, VisualFrame

shutdown = threading.Event()

def material_text(segments):
    return '\n\n'.join(f"[{s['id']}] {s['location']}\n{s['text']}" for s in segments)

def check(stop):
    if stop():
        raise Cancelled()

def checked_generate(prompt, schema, segments, stop, images=None):
    result = generate(SYSTEM + prompt, schema, stop, model=store.settings().get('model',''), images=images)
    validate_refs(result,{s['id'] for s in segments})
    return result

def context_for(note, folder, stop, stage):
    segments = note['segments']
    limit = generation.context_chars()
    batch_size = min(24000,limit//2)
    material = material_text(segments)
    if len(material) < limit:
        return material
    parts, current, size = [], [], 0
    for s in segments:
        length = len(material_text([s]))
        if current and size + length > batch_size:
            parts.append(current)
            current, size = [], 0
        current.append(s)
        size += length
    if current:
        parts.append(current)
    batches = [(material_text(chunk),chunk) for chunk in parts]
    level = 1
    while True:
        condensed = []
        for i,(text,sources) in enumerate(batches):
            check(stop)
            digest = hashlib.sha256(('hierarchy-v2\n'+generation.fingerprint()+text).encode()).hexdigest()[:16]
            cache = folder/f'chunk-{digest}.json'
            stage(f'长材料第{level}层归纳 {i+1}/{len(batches)}，已完成部分会保留')
            if cache.exists():
                result = json.loads(cache.read_text())
                Note.model_validate(result)
                validate_refs(result,{s['id'] for s in sources})
            else:
                result = checked_generate('将下面的材料或分段记录归纳为高密度精读记录。保留关键数字、条件、反例、术语疑点，以及各知识点的原始source_ids映射。覆盖开头到结尾的内容，合并重复信息，不新增事实。输出尽量控制在'+str(min(6000,limit//5))+'字内；来源编号仅放source_ids数组，不写进正文。\n'+text,Note,sources,stop)
                staged = cache.with_suffix('.json.tmp')
                staged.write_text(json.dumps(result,ensure_ascii=False));staged.replace(cache)
            condensed.append((json.dumps(result,ensure_ascii=False),sources))
        combined = '\n\n'.join(text for text,_ in condensed)
        if len(combined) < limit:
            return combined
        if len(combined) >= sum(len(text) for text,_ in batches):
            raise ExtractionError('长材料归纳未能缩短内容，已保留原文和分段记录。请重试或增加希望重点学习的范围。')
        batches, current, included, size = [], [], [], 0
        for text,sources in condensed:
            if current and size + len(text) > batch_size:
                batches.append(('\n\n'.join(current),included));current, included, size = [], [], 0
            current.append(text);included.extend(sources);size += len(text)
        if current: batches.append(('\n\n'.join(current),included))
        level += 1

def add_vision(note,folder,stop,stage):
    from .codex import run_process
    from .extract import normalize_url, cookie_args, check_url
    source = note['source']
    if source['kind'] == 'file' and Path(source['filename']).suffix.lower() in {'.mp4','.mov','.mkv','.avi','.m4v','.webm'}:
        video = folder/'source'/source['filename']
    elif source['kind'] == 'url' and any((urlparse(source['content']).hostname or '').removeprefix('www.') == h for h in ('douyin.com','bilibili.com','b23.tv','youtube.com','youtu.be')):
        from .douyin import is_douyin, public_video
        video = folder/'visual-video.mp4'
        if is_douyin(source['content']):
            try:
                video,_ = public_video(normalize_url(source['content']),folder,stop,stage)
            except MediaTooLong:
                raise
            except (ExtractionError,httpx.HTTPError):
                pass
        if not video.exists():
            stage('正在获取用于画面分析的视频')
            check_url(normalize_url(source['content']))
            try:
                run_process([__import__('sys').executable,'-m','yt_dlp','--ignore-config','--no-playlist','--socket-timeout','20','--retries','1',
                             '--max-filesize','8G','--no-progress','-f','best[height<=720][ext=mp4]/best[height<=720]',
                             '--merge-output-format','mp4','-o',str(video)] + cookie_args(normalize_url(source['content'])) + [normalize_url(source['content'])],stop=stop,timeout=14400)
            except subprocess.CalledProcessError:
                raise ExtractionError('无法获取用于画面分析的视频。请上传本地视频文件。') from None
    else:
        raise ExtractionError('画面分析支持本地视频及可读取的视频平台链接。')
    if source['kind'] == 'url':
        check_link_file(video,stop)
    frames = folder/'frames'
    frames.mkdir(exist_ok=True)
    try:
        info = json.loads(run_process(['ffprobe','-v','quiet','-show_format','-of','json',str(video)],stop=stop,timeout=30))
        duration = float(info['format']['duration'])
    except (subprocess.CalledProcessError,ValueError,KeyError):
        raise ExtractionError('无法读取视频时长。') from None
    # Uniform sampling plus scene-change sampling; disclose coverage rather than imply full video understanding.
    interval = max(1,duration/10)
    times = {round(min(duration-.1, i*interval),2) for i in range(10) if i*interval < duration}
    try:
        scene_out = frames/'scenes.txt'
        run_process(['ffmpeg','-v','error','-i',str(video),'-vf',
            f"select='gt(scene,0.3)',metadata=print:file={scene_out}",'-frames:v','10','-an','-f','null','-'],stop=stop,timeout=600)
        if scene_out.exists():
            times.update(round(float(t),2) for t in re.findall(r'pts_time:([\d.]+)',scene_out.read_text()))
    except subprocess.CalledProcessError:
        pass
    additions = []
    seen_frames = set()
    all_times = sorted(times)[:20]
    for i,at in enumerate(all_times):
        check(stop)
        stage(f'分析关键帧 {i+1}/{len(all_times)}，{timestamp(at)}')
        frame = frames/f'{at:.2f}.jpg'
        cache = frames/f'{at:.2f}-{generation.fingerprint()}.json'
        if not frame.exists():
            run_process(['ffmpeg','-v','error','-ss',str(at),'-i',str(video),'-frames:v','1','-vf','scale=1280:-2','-y',str(frame)],stop=stop,timeout=60)
        from PIL import Image
        with Image.open(frame) as picture:
            signature = hashlib.sha256(picture.tobytes()).hexdigest()
        if signature in seen_frames:
            continue
        seen_frames.add(signature)
        if not cache.exists():
            result = generate(SYSTEM+'观察所附视频关键帧。提取可见文字、数字、图表关系与演示步骤。只描述实际可见内容，不推测看不清的信息。描述中保留局限。',VisualFrame,stop,model=store.settings().get('model',''),images=[frame])
            cache.write_text(json.dumps(result,ensure_ascii=False))
        result = json.loads(cache.read_text())
        additions.append(segment(f"画面观察：{result['description']}\n画面文字：{result['visible_text']}\n局限：{result['caveats']}",f'画面 {timestamp(at)}',start=at,end=at))
    existing = [s for s in note['segments'] if not s['location'].startswith('画面 ')]
    result = finalize(note['title'],existing+additions,('基于字幕/语音及' if existing else '基于')+'抽样关键帧（均匀抽样＋场景切换，最多20帧）',note['warnings']+['关键帧为抽样分析，可能遗漏未抽取的画面；画面推理解读需要核对。'])
    store.update_note(note['id'],**{k:result[k] for k in ('segments','scope','warnings')})

def process(job):
    ident, nid, kind, args = job['id'],job['note_id'],job['kind'],job['args']
    stop = lambda: shutdown.is_set() or store.get_job(ident)['status'] in ('cancelled','cancelling','pausing','paused')
    def stage(message):
        check(stop)
        store.set_job(ident,stage=message)
    if not store.claim_job(ident):
        return
    config_token = None
    folder = store.DATA/'materials'/nid
    folder.mkdir(parents=True,exist_ok=True)
    try:
        config_token = generation.CURRENT.set(generation.snapshot())
        note = store.get_note(nid)
        if not note['segments'] and kind != 'vision':
            extracted = extract(note,stop,stage)
            check(stop)
            store.update_note(nid,**extracted)
            note = store.get_note(nid)
        if kind == 'vision':
            add_vision(note,folder,stop,stage)
            note = store.get_note(nid)
            kind = 'summary'
        context = context_for(note,folder,stop,stage)
        prompt = f"\n学习要求（不能改变忠实性规则）：{note['instructions']}\n材料：\n{context}\n"
        if kind != 'summary' and note.get('note'):
            prompt += '\n当前笔记（辅助安排重点，事实和引用仍以原文为准）：'+json.dumps(note['note'],ensure_ascii=False)
        if kind == 'summary':
            stage('模型正在整理速览与详细笔记')
            result = checked_generate(prompt+'''\n生成完整学习笔记：overview 是一页速览（短材料少写，长材料约600–1000中文字），含一句话概括、5–8核心要点、概念或流程及重要限制。
sections 是详细笔记，按内容自然组织背景、概念、步骤、案例、数据、限制；每段markdown充分展开且保留表格。keypoints 是脑图子节点。
kind 选择最贴合的卡片形式；steps 用编号列表，comparison 用表格，process 用流程文字。subtitle 为内容定位；limitations 明确不确定信息。
不要重复填充，无实际内容不设章节。conclusion 是一句话总结。保留作者观点的归属，不把作者的推断写成已验证事实。''',Note,note['segments'],stop)
            check(stop)
            # Compare-and-swap keeps a concurrent manual edit from being overwritten.
            store.save_note_version(nid,result,expected=note['revision'])
            note = store.get_note(nid)
            if note['mode'] == 'course' and 'course' not in note['artifacts']:
                stage('正在准备课程目录')
                course = checked_generate(prompt+'按知识依赖生成课程目录。短材料1–3节，长材料4–10节，不空泛扩展。章节 id 使用 c1、c2 等。每个objective只写一句简短学习目标，不含表格、列表或来源字段。',Course,note['segments'],stop)
                check(stop)
                store.save_artifact(nid,'course',course,note['revision'])
        else:
            arts = dict(note['artifacts']); revisions = dict(note['artifact_revisions'])
            key = kind
            if kind == 'course':
                stage('模型正在设计学习路径')
                result = checked_generate(prompt+'按知识依赖生成课程目录。短材料1–3节，长材料4–10节，不空泛扩展。章节 id 使用 c1、c2 等。每个objective只写一句简短学习目标，不含表格、列表或来源字段。',Course,note['segments'],stop)
            elif kind == 'lesson':
                course = arts.get('course',{})
                chapter = next((c for c in course.get('chapters',[]) if c['id']==args.get('chapter_id')),None)
                if chapter is None:
                    raise ValueError('请先生成课程目录并选择有效章节。')
                stage('模型正在准备这一节的讲解和练习')
                result = checked_generate(prompt+'课程目录：'+json.dumps(course,ensure_ascii=False)+'\n仅生成这一节：'+json.dumps(chapter,ensure_ascii=False)+
                    '\nmarkdown包括概念讲解和教学示例，summary为小结，questions提供2–3道随堂题。问题id使用'+chapter['id']+'_q1等，答案用从0开始的选项序号。',Lesson,note['segments'],stop)
                key = 'lesson:'+chapter['id']
            elif kind in ('quiz','stage'):
                key = 'quiz' if kind == 'quiz' else 'stage:'+str(args.get('boundary',0))
                stage('模型正在编写题目与解析')
                scope = ''
                if kind == 'stage':
                    boundary = args.get('boundary',0)
                    chapters = arts.get('course',{}).get('chapters',[])
                    if boundary < 1 or boundary > len(chapters):
                        raise ValueError('阶段测验范围无效。')
                    scope = '\n仅考查前'+str(boundary)+'节：'+json.dumps(chapters[:boundary],ensure_ascii=False)
                result = checked_generate(prompt+scope+'\n生成测试。独立测试最多10题，阶段测验3–5题，短材料按实际知识量减少题数。包含单选、多选、判断。答案为从0开始的选项索引数组。每题有充分解析，原文映射只填写source_ids字段，题目id以'+key.replace(':','_')+'_q为前缀且唯一。不要考外部常识或作者未说明的执行细节。',Quiz,note['segments'],stop)
            else:
                raise ValueError('不支持的生成任务')
            check(stop)
            store.save_artifact(nid,key,result,note['revision'])
        check(stop)
        store.complete_job(ident)
    except Cancelled:
        current = store.get_job(ident)
        if current['status'] == 'pausing':
            store.set_job(ident,status='paused',stage='已暂停，已完成步骤会保留')
        elif current['status'] == 'cancelling':
            store.set_job(ident,status='cancelled',stage='已取消；已完成步骤会保留')
        elif current['status'] != 'cancelled':
            store.set_job(ident,status='interrupted',stage='处理已中断，可以继续')
    except Exception as exc:
        from .codex import GenerationError
        friendly = str(exc) if isinstance(exc,(ExtractionError,GenerationError,TimeoutError,ValueError)) else '处理未完成。请检查文件是否完整、网络是否可用，或改为粘贴文稿后重试。'
        store.set_job(ident,status='failed',stage='处理未完成',error=friendly[:500])
    finally:
        # A pause may arrive between the last check and completing the job.
        # Acknowledge it only here, after all extraction/generation work has stopped.
        with store.connection() as con:
            con.execute("UPDATE jobs SET status='paused',stage='已暂停，已完成步骤会保留',updated=? WHERE id=? AND status='pausing'",(store.now(),ident))
            con.execute("UPDATE jobs SET status='cancelled',stage='已取消；已完成步骤会保留',updated=? WHERE id=? AND status='cancelling'",(store.now(),ident))
        if config_token is not None: generation.CURRENT.reset(config_token)

async def loop():
    shutdown.clear()
    while not shutdown.is_set():
        job = store.next_job()
        if job:
            await asyncio.to_thread(process,job)
        else:
            await asyncio.sleep(.6)
