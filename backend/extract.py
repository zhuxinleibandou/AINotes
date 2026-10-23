import ipaddress
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup
from . import store
from .codex import Cancelled, run_process

class ExtractionError(Exception):
    pass

class MediaTooLong(ExtractionError):
    pass

MAX_LINK_SECONDS = 600 * 60
TRANSCRIBE_CHUNK_SECONDS = 20 * 60

def link_duration(value):
    """Return a known duration, or None; a duration over the limit is never retried via another reader."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(seconds) or seconds <= 0:
        return None
    if seconds > MAX_LINK_SECONDS:
        raise MediaTooLong('单条链接的音视频最长支持600分钟（10小时）。这份材料超过限制，请使用较短链接或上传本地文件。')
    return seconds

def probe_duration(path, stop):
    try:
        info = json.loads(run_process(['ffprobe','-v','quiet','-show_format','-show_streams','-of','json',str(path)],stop=stop,timeout=30))
        durations = [info.get('format',{}).get('duration')] + [s.get('duration') for s in info.get('streams',[])]
        values = []
        for value in durations:
            try: seconds = float(value)
            except (TypeError,ValueError): continue
            if math.isfinite(seconds) and seconds > 0: values.append(seconds)
        if values: return max(values)
    except (subprocess.CalledProcessError,ValueError):
        pass
    raise ExtractionError('无法确认音视频时长，请换用完整文件或可读取的链接。')

def check_link_file(path, stop):
    return link_duration(probe_duration(path,stop))

MEDIA_HOSTS = {'youtube.com','youtu.be','bilibili.com','b23.tv','douyin.com','iesdouyin.com'}
AUDIO = {'.mp3','.m4a','.wav','.aac','.ogg','.flac','.webm'}
VIDEO = {'.mp4','.mov','.mkv','.avi','.m4v'}
TEXT = {'.md','.markdown','.txt'}
IMAGES = {'.png','.jpg','.jpeg','.webp','.bmp','.tiff','.heic'}
ALLOWED = AUDIO | VIDEO | TEXT | IMAGES | {'.pdf','.docx','.pptx'}

def check_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ExtractionError('请输入公开的 HTTPS 链接。')
    host = parsed.hostname.rstrip('.').lower()
    if host in {'localhost'} or host.endswith('.local'):
        raise ExtractionError('不能读取本机或局域网链接。')
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ExtractionError('无法连接来源网站，请检查链接和网络。') from None
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        # Respect the user's existing fake-IP proxy, but never direct fake-IP input.
        proxy = ip in ipaddress.ip_network('198.18.0.0/15') and not re.fullmatch(r'[\d.]+', host)
        if not ip.is_global and not proxy:
            raise ExtractionError('不能读取本机、局域网或保留地址。')
    return url

def fetch(url, *, destination=None, limit=8_000_000, stop=lambda:False):
    with httpx.Client(timeout=35, follow_redirects=False, headers={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36'}) as client:
        for _ in range(6):
            check_url(url)
            with client.stream('GET', url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get('location',''))
                    continue
                if response.status_code >= 400:
                    raise ExtractionError(f'来源网站拒绝访问（{response.status_code}）。可以上传文件或粘贴文稿。')
                count, chunks = 0, []
                staged = destination.with_name(destination.name+'.partial') if destination else None
                target = staged.open('wb') if staged else None
                try:
                    for chunk in response.iter_bytes():
                        if stop():
                            raise Cancelled()
                        count += len(chunk)
                        if count > limit:
                            raise ExtractionError('材料超过当前大小限制，请上传较小文件或分段处理。')
                        if target:
                            target.write(chunk)
                        else:
                            chunks.append(chunk)
                except BaseException:
                    if target: target.close()
                    if staged: staged.unlink(missing_ok=True)
                    raise
                finally:
                    if target: target.close()
                if staged: staged.replace(destination)
                return b''.join(chunks), url, response.headers.get('content-type','')
    raise ExtractionError('链接跳转次数过多，请使用内容的直接链接。')

def normalize_url(value):
    match = re.search(r'https://[^\s<>"，。！]+', value)
    if not match:
        raise ExtractionError('没有找到有效链接，请粘贴完整的分享链接。')
    url = match.group().rstrip('，。,.）)')
    parsed = urlparse(url)
    if (parsed.hostname or '') == 'douyin.com' or (parsed.hostname or '').endswith('.douyin.com'):
        from urllib.parse import parse_qs
        ident = parse_qs(parsed.query).get('modal_id',[''])[0]
        if ident.isdigit():
            url = 'https://www.douyin.com/video/' + ident
    return url

def segment(text, location, *, start=None, end=None):
    return {'id':'', 'text':text.strip(), 'location':location, 'start':start, 'end':end}

def finalize(title, segments, scope, warnings=None):
    final = []
    for part in segments:
        if not part['text'].strip():
            continue
        # Keep every character and location; a bounded segment prevents one huge paragraph.
        text = part['text']
        for offset in range(0, len(text), 4500):
            final.append({**part, 'id': f's{len(final)+1}', 'text': text[offset:offset+4500]})
    if sum(len(s['text']) for s in final) < 15:
        raise ExtractionError('没有提取到足够的正文或清晰语音。请检查材料，或改为粘贴文稿。')
    return {'title':title, 'segments':final, 'scope':scope, 'warnings':warnings or []}

def ocr(path, stop):
    binary = store.DATA / 'cache' / 'vision-ocr'
    binary.parent.mkdir(exist_ok=True)
    source = Path(__file__).with_name('ocr.swift')
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        if not shutil.which('swiftc'):
            raise ExtractionError('本地 OCR 需要 Apple 命令行工具。请安装后重试，或粘贴正文。')
        run_process(['swiftc', str(source), '-o',str(binary)], stop=stop, timeout=120)
    try:
        return run_process([str(binary),str(path)],stop=stop,timeout=90).decode().strip()
    except subprocess.CalledProcessError:
        raise ExtractionError('图片文字识别失败，请换用清晰图片或粘贴正文。') from None

def timestamp(seconds):
    return f'{int(seconds)//3600:02}:{int(seconds)//60%60:02}:{int(seconds)%60:02}'

def transcribe(path, folder, stop, stage):
    cached = folder/'transcript.json'
    if cached.exists():
        try: json.loads(cached.read_text())
        except (ValueError,OSError): cached.unlink(missing_ok=True)
    if not cached.exists():
        duration = probe_duration(path,stop)
        count = math.ceil(duration / TRANSCRIBE_CHUNK_SECONDS)
        parts = []
        for index in range(count):
            if stop(): raise Cancelled()
            start = index * TRANSCRIBE_CHUNK_SECONDS
            part = folder/f'transcript-part-{start}.json'
            audio = folder/f'transcript-part-{start}.wav'
            stage(f'本地语音转写 {index+1}/{count}，已完成分段会保留；首次使用需下载模型')
            if part.exists():
                try: json.loads(part.read_text())
                except (ValueError,OSError): part.unlink(missing_ok=True)
            if not part.exists():
                try:
                    run_process(['ffmpeg','-v','error','-ss',str(start),'-i',str(path),'-t',str(TRANSCRIBE_CHUNK_SECONDS),
                                 '-vn','-ac','1','-ar','16000','-c:a','pcm_s16le','-y',str(audio)],stop=stop,timeout=300)
                    run_process([sys.executable, '-m', 'backend.transcribe', str(audio), store.settings()['whisper_model'], str(part)],
                                stop=stop, timeout=3600, cwd=str(store.ROOT), env={**os.environ,'HF_HUB_DISABLE_XET':'1'})
                except subprocess.CalledProcessError:
                    raise ExtractionError('本地转写未完成。已完成的分段会保留，请检查模型下载网络、音频内容和磁盘空间后重试。') from None
                finally:
                    audio.unlink(missing_ok=True)
            parts.extend({**s,'start':s['start']+start,'end':s['end']+start} for s in json.loads(part.read_text()))
        staged = cached.with_suffix('.json.tmp')
        staged.write_text(json.dumps(parts,ensure_ascii=False));staged.replace(cached)
    parts = json.loads(cached.read_text())
    return [segment(s['text'],f"语音 {timestamp(s['start'])}–{timestamp(s['end'])}",start=s['start'],end=s['end']) for s in parts]

def subtitle_segments(raw, fmt):
    if fmt == 'json3':
        data = json.loads(raw)
        parts = []
        for event in data.get('events',[]):
            text = ''.join(s.get('utf8','') for s in event.get('segs',[])).strip()
            start = event.get('tStartMs',0)/1000
            end = start + event.get('dDurationMs',0)/1000
            if text:
                parts.append(segment(text, f'字幕 {timestamp(start)}',start=start,end=end))
        return parts
    text = raw.decode('utf-8-sig',errors='replace')
    parts = []
    for block in re.split(r'\n\s*\n',text):
        lines = block.splitlines()
        timing = next((i for i,line in enumerate(lines) if '-->' in line),None)
        if timing is None:
            continue
        matches = list(re.finditer(r'(?:(\d+):)?(\d+):(\d+[.,]\d+)', lines[timing]))
        match = matches[0] if matches else None
        if not match:
            continue
        start = int(match[1] or 0)*3600 + int(match[2])*60 + float(match[3].replace(',','.'))
        body = BeautifulSoup('\n'.join(lines[timing+1:]),'html.parser').get_text(' ',strip=True)
        if body and (not parts or parts[-1]['text'] != body):
            parts.append(segment(body, f'字幕 {timestamp(start)}',start=start,end=(int(matches[1][1] or 0)*3600+int(matches[1][2])*60+float(matches[1][3].replace(',','.'))) if len(matches)>1 else None))
    return parts

def cookie_args(url):
    host=(urlparse(url).hostname or '').lower()
    mapping={'douyin':('douyin.com','iesdouyin.com'),'youtube':('youtube.com','youtu.be'),'bilibili':('bilibili.com','b23.tv')}
    for name,domains in mapping.items():
        if any(host==domain or host.endswith('.'+domain) for domain in domains):
            path=store.DATA/'secrets'/(name+'-cookies.txt')
            if path.is_file():return ['--cookies',str(path)]
    return []


def media_url(url, folder, stop, stage):
    from .douyin import is_douyin, public_video
    if is_douyin(url):
        try:
            video, info = public_video(url,folder,stop,stage)
        except MediaTooLong:
            raise
        except (ExtractionError,httpx.HTTPError):
            stage('公开分享页暂不可读，正在尝试常规平台读取')
        else:
            return finalize(info['title'],transcribe(video,folder,stop,stage),
                '基于抖音公开分享页音频转写；未分析视频画面',
                ['自动使用网站下发的临时游客会话，不读取浏览器登录信息；转写中的术语和数字需要核对。'])
    metadata = folder/'media-meta.json'
    stage('正在获取视频信息和可用字幕')
    common = [sys.executable,'-m','yt_dlp','--ignore-config','--no-playlist','--socket-timeout','20','--retries','1','--no-warnings'] + cookie_args(url)
    try:
        if not metadata.exists():
            out = run_process(common + ['--dump-single-json','--skip-download',url],stop=stop,timeout=120)
            metadata.write_bytes(out)
        info = json.loads(metadata.read_text())
    except (subprocess.CalledProcessError, ValueError):
        raise ExtractionError('无法读取该平台的内容，可能需要登录或触发访问限制。请使用公开分享链接，或上传音视频、粘贴文稿。') from None
    if info.get('is_live'):
        raise ExtractionError('直播尚未结束，无法确认完整时长。请在直播结束后使用回放链接。')
    duration = link_duration(info.get('duration'))
    # Unknown duration must be checked against the downloaded media, never accepted via subtitles alone.
    subs = (info.get('subtitles') or info.get('automatic_captions') or {}) if duration else {}
    for lang in sorted(subs,key=lambda s:(not s.startswith('zh'),not s.startswith('en'),s)):
        if not lang.startswith(('zh','en')):
            continue
        tracks = sorted(subs[lang],key=lambda x:x.get('ext')!='json3')
        for track in tracks:
            if track.get('ext') not in ('json3','vtt','srt'):
                continue
            try:
                raw,_,_ = fetch(track['url'],stop=stop)
                parts = subtitle_segments(raw,track['ext'])
                if parts:
                    link_duration(max((s.get('end') or s.get('start') or 0) for s in parts))
                    return finalize(info.get('title','视频笔记'),parts,'基于平台字幕；未分析视频画面',['字幕可能存在自动识别误差。'])
            except MediaTooLong:
                raise
            except (ExtractionError, httpx.HTTPError, ValueError):
                continue
    stage('没有可用字幕，正在获取音轨')
    target = folder/'media.m4a'
    if not target.exists():
        try:
            run_process(common + ['-f','bestaudio/best','--max-filesize','8G','--no-progress','-x','--audio-format','m4a',
                                   '-o',str(folder/'media.%(ext)s'),url],stop=stop,timeout=14400)
        except subprocess.CalledProcessError:
            raise ExtractionError('无法下载该平台音频。请上传本地音视频或粘贴文稿。') from None
    if not target.exists():
        raise ExtractionError('没有获取到音频文件。可以改为上传材料。')
    check_link_file(target,stop)
    return finalize(info.get('title','视频笔记'),transcribe(target,folder,stop,stage),'基于音频转写；未分析视频画面')

def extract(note, stop, stage):
    source = note['source']
    folder = store.DATA / 'materials' / note['id']
    folder.mkdir(parents=True,exist_ok=True)
    if source['kind'] == 'text':
        text = source['content'].strip()
        title = note['title'] if note['title'] != '正在整理材料' else text.splitlines()[0].lstrip('# ')[:80]
        return finalize(title,[segment(t, f'正文第 {i+1} 段') for i,t in enumerate(re.split(r'\n\s*\n',text))],'基于粘贴正文')
    if source['kind'] == 'url':
        url = normalize_url(source['content'])
        host = (urlparse(url).hostname or '').lower()
        check_url(url)
        if Path(urlparse(url).path).suffix.lower() in AUDIO | VIDEO:
            path = folder/('linked-media'+Path(urlparse(url).path).suffix.lower())
            if not path.exists():
                stage('正在获取音视频文件')
                fetch(url,destination=path,limit=8*1024**3,stop=stop)
            check_link_file(path,stop)
            return finalize(path.stem,transcribe(path,folder,stop,stage),'基于链接音频转写；未分析视频画面')
        if any(host == h or host.endswith('.'+h) for h in MEDIA_HOSTS):
            return media_url(url,folder,stop,stage)
        stage('正在提取网页正文')
        raw, final_url, mime = fetch(url,stop=stop)
        if 'application/pdf' in mime:
            path = folder/'source.pdf'
            path.write_bytes(raw)
        else:
            soup = BeautifulSoup(raw,'html.parser')
            title = soup.title.get_text(strip=True) if soup.title else host
            if (host=='xiaoyuzhoufm.com' or host.endswith('.xiaoyuzhoufm.com')):
                audio = soup.select_one('audio[src], audio source[src],meta[property="og:audio"],meta[property="og:audio:url"]')
                candidate = (audio.get('src') or audio.get('content')) if audio else None
                if not candidate:
                    embedded = soup.find('script',id='__NEXT_DATA__')
                    def find_audio(obj):
                        if isinstance(obj,dict):
                            for k,v in obj.items():
                                if k in ('url','src','contentUrl') and isinstance(v,str) and re.search(r'\.(mp3|m4a)(\?|$)',v):
                                    return v
                                found = find_audio(v)
                                if found:
                                    return found
                        if isinstance(obj,list):
                            for v in obj:
                                found = find_audio(v)
                                if found:
                                    return found
                        return None
                    candidate = find_audio(json.loads(embedded.string or '{}')) if embedded else None
                if not candidate:
                    raise ExtractionError('未获取到小宇宙单集音频。请使用单集分享页，或上传音频文件。')
                audio_path = folder/'podcast.m4a'
                if not audio_path.exists():
                    fetch(urljoin(final_url,candidate),destination=audio_path,limit=8*1024**3,stop=stop)
                check_link_file(audio_path,stop)
                return finalize(title,transcribe(audio_path,folder,stop,stage),'基于播客音频转写')
            article = soup.select_one('#js_content') if host == 'mp.weixin.qq.com' else None
            if host == 'mp.weixin.qq.com' and article is None:
                raise ExtractionError('没有获取到公众号文章正文。请使用具体文章链接，或直接粘贴文章正文。')
            if article:
                text = article.get_text('\n',strip=True)
            else:
                import trafilatura
                text = trafilatura.extract(raw, include_tables=True, output_format='markdown') or ''
            if len(text.strip()) < 120 or any(s in text[:200] for s in ('访问过于频繁','环境异常','请完成安全验证','验证后继续访问','Just a moment')):
                raise ExtractionError('未取得完整正文，可能是登录页或验证页面。请粘贴文章正文，或上传文件。')
            return finalize(title,[segment(t,f'网页第 {i+1} 段') for i,t in enumerate(re.split(r'\n\s*\n',text))],'基于网页正文',['网页提取可能遗漏图片中的信息。'])
    else:
        path = folder / 'source' / source['filename']
    return extract_file(path,folder,stop,stage)

def extract_file(path, folder, stop, stage):
    ext = path.suffix.lower()
    stage('正在解析文件')
    title = path.stem
    if ext in TEXT:
        data = path.read_bytes()
        for encoding in ['utf-8-sig','utf-16','gb18030']:
            try:
                text = data.decode(encoding)
                break
            except UnicodeError:
                continue
        else:
            raise ExtractionError('无法识别文本编码，请另存为 UTF-8 后上传。')
        return finalize(title,[segment(t, f'正文第 {i+1} 段') for i,t in enumerate(re.split(r'\n\s*\n',text))],'基于文件正文')
    if ext == '.pdf':
        import pymupdf as fitz
        parts, scanned = [], False
        try:
            doc = fitz.open(path)
            if doc.needs_pass:
                raise ExtractionError('PDF 已加密，请上传解密后的文件。')
            for i,page in enumerate(doc):
                if stop():
                    raise Cancelled()
                stage(f'正在解析 PDF，第 {i+1}/{len(doc)} 页')
                text = page.get_text(sort=True).strip()
                if len(text) < 35:
                    image = folder/'ocr-page.png'
                    page.get_pixmap(matrix=fitz.Matrix(2,2)).save(image)
                    text = ocr(image,stop)
                    scanned = True
                parts.append(segment(text, f'第 {i+1} 页'))
            doc.close()
        except (ValueError,RuntimeError):
            raise ExtractionError('PDF 损坏或无法读取，请换用完整文件。') from None
        return finalize(title,parts,'基于 PDF 正文'+('及本地 OCR' if scanned else ''),['OCR 结果中的数字和复杂表格需要核对。'] if scanned else [])
    if ext == '.pptx':
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        parts = []
        deck = Presentation(path)
        for i,slide in enumerate(deck.slides):
            contents = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    contents.append(shape.text)
                if shape.has_table:
                    rows = [[cell.text.replace('\n',' ') for cell in row.cells] for row in shape.table.rows]
                    if rows:
                        contents.append('\n'.join(['|'+'|'.join(rows[0])+'|','|'+'|'.join('---' for _ in rows[0])+'|']+['|'+'|'.join(r)+'|' for r in rows[1:]]))
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    image = folder / ('ppt-image.' + shape.image.ext)
                    image.write_bytes(shape.image.blob)
                    contents.append(ocr(image,stop))
            parts.append(segment('\n\n'.join(contents),f'第 {i+1} 张幻灯片'))
        return finalize(title,parts,'基于幻灯片文字、表格及图片 OCR',['图形布局与复杂图表可能需要对照原文件核查。'])
    if ext == '.docx':
        from markitdown import MarkItDown
        from docx import Document
        from io import BytesIO
        text = MarkItDown(enable_plugins=False).convert_local(str(path)).text_content
        parts = [segment(t,f'文档第 {i+1} 段') for i,t in enumerate(re.split(r'\n\s*\n',text))]
        document = Document(path)
        for i,rel in enumerate(document.part.rels.values()):
            if 'image' in rel.reltype and not rel.is_external:
                image = folder/('word-image'+Path(str(rel.target_part.partname)).suffix)
                image.write_bytes(rel.target_part.blob)
                parts.append(segment(ocr(image,stop),f'文档插图 {i+1}'))
        return finalize(title,parts,'基于 Word 正文、表格及图片 OCR')
    if ext in IMAGES:
        return finalize(title,[segment(ocr(path,stop),'图片文字')],'基于本地图片 OCR',['本次识别图片中的文字；复杂图表和视觉关系请对照原图。'])
    if ext in AUDIO | VIDEO:
        return finalize(title,transcribe(path,folder,stop,stage),'基于音频转写；未分析视频画面' if ext in VIDEO else '基于音频转写',['语音转写可能有同音词、术语或数字误差，请对照原始音频核查。'])
    raise ExtractionError('此格式暂不支持。旧版 Word/PPT 请另存为 DOCX/PPTX。')
