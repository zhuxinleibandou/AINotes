"""Read public Douyin share pages with a temporary anonymous visitor session.

No browser profile, login Cookie, signature service or third-party API is used.
Only the public page's own Set-Cookie responses are kept, in memory, for this request.
"""
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse
import httpx
from .codex import Cancelled, run_process
from .extract import ExtractionError, MediaTooLong, check_url, link_duration, check_link_file

MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
HOSTS = ('douyin.com', 'iesdouyin.com')

def is_douyin(url):
    host = (urlparse(url).hostname or '').lower()
    return any(host == h or host.endswith('.'+h) for h in HOSTS)

def _read(client, url, stop, destination=None):
    for _ in range(6):
        if stop(): raise Cancelled()
        check_url(url)
        with client.stream('GET', url) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get('location',''))
                continue
            if response.status_code not in (200,206):
                raise ExtractionError(f'抖音公开内容读取失败（{response.status_code}）。')
            mime = response.headers.get('content-type','').split(';')[0].lower()
            if destination and not (mime.startswith(('video/','audio/')) or mime == 'application/octet-stream'):
                raise ExtractionError('播放地址未返回音视频文件。')
            limit = 8*1024**3 if destination else 8*1024*1024
            staged = destination.with_suffix('.mp4.partial') if destination else None
            handle = staged.open('wb') if staged else None
            chunks, size = [], 0
            try:
                for chunk in response.iter_bytes():
                    if stop(): raise Cancelled()
                    size += len(chunk)
                    if size > limit: raise ExtractionError('抖音材料超过大小限制，请分段上传。')
                    if handle: handle.write(chunk)
                    else: chunks.append(chunk)
            except BaseException:
                if handle: handle.close()
                if staged: staged.unlink(missing_ok=True)
                raise
            finally:
                if handle: handle.close()
            if staged: staged.replace(destination)
            return b''.join(chunks),url
    raise ExtractionError('抖音链接跳转次数过多。')

def parse_share(html, ident):
    def find(value):
        if isinstance(value,dict):
            if str(value.get('aweme_id','')) == ident and isinstance(value.get('video'),dict):
                return value
            children = value.values()
        elif isinstance(value,list): children = value
        else: return None
        for child in children:
            result = find(child)
            if result is not None: return result
        return None
    for match in re.finditer(r'(?:window\.)?_ROUTER_DATA\s*=\s*',html):
        try: data = json.JSONDecoder().raw_decode(html[match.end():])[0]
        except ValueError: continue
        item = find(data)
        if item:
            urls = item['video'].get('play_addr',{}).get('url_list',[])
            urls = [u for u in urls if isinstance(u,str) and urlparse(u).scheme == 'https']
            if urls:
                duration = item['video'].get('duration')
                return {'id':ident,'title':item.get('desc','抖音视频')[:300], 'urls':urls[:3],
                        'duration':float(duration)/1000 if isinstance(duration,(int,float)) else None}
    return None

def _verify(path, stop):
    try:
        value = json.loads(run_process(['ffprobe','-v','quiet','-show_streams','-of','json',str(path)],stop=stop,timeout=30))
        if not any(s.get('codec_type') in ('video','audio') for s in value.get('streams',[])):
            raise ValueError('no streams')
    except (ValueError, subprocess.CalledProcessError):
        raise ExtractionError('取得的抖音文件不是有效音视频，未继续生成。') from None

def public_video(url, folder:Path, stop, stage):
    if not is_douyin(url): raise ExtractionError('不是抖音链接。')
    folder.mkdir(parents=True,exist_ok=True)
    with httpx.Client(timeout=35,follow_redirects=False,headers={'User-Agent':MOBILE_UA}) as client:
        match = re.search(r'/(?:video|note)/(\d+)',urlparse(url).path)
        if not match:
            # Short share links can resolve to a public detail page.
            _,resolved = _read(client,url,stop)
            if not is_douyin(resolved): raise ExtractionError('分享链接没有指向抖音作品。')
            match = re.search(r'/(?:video|note)/(\d+)',urlparse(resolved).path)
        if not match: raise ExtractionError('未找到抖音作品编号。')
        ident = match[1]
        video, cache = folder/'douyin-video.mp4', folder/'douyin-public.json'
        if video.exists() and cache.exists():
            try:
                info = json.loads(cache.read_text())
                if info['id'] != ident: raise ValueError('id mismatch')
                _verify(video,stop)
                check_link_file(video,stop)
                return video,info
            except MediaTooLong:
                raise
            except (ValueError,KeyError,ExtractionError):
                # Only disposable download checkpoints are removed; source notes are untouched.
                video.unlink(missing_ok=True)
                cache.unlink(missing_ok=True)
        share = f'https://www.iesdouyin.com/share/video/{ident}/'
        info = None
        for attempt in range(3):
            stage(f'正在读取抖音公开分享页 {attempt+1}/3（自动游客会话）')
            raw,_ = _read(client,share,stop)
            info = parse_share(raw.decode('utf-8',errors='replace'),ident)
            if info: break
        if not info: raise ExtractionError('公开分享页没有返回这条视频，可能受访问限制或已不可用。')
        link_duration(info.get('duration'))
        stage('已取得公开播放地址，正在获取音视频')
        for candidate in info['urls']:
            try:
                _read(client,candidate,stop,video)
                _verify(video,stop)
                duration = check_link_file(video,stop)
                # Avoid persisting expiring playback URLs or anonymous session identifiers.
                saved = {'id':ident,'title':info['title'],'duration':duration}
                temp = cache.with_suffix('.json.tmp');temp.write_text(json.dumps(saved,ensure_ascii=False));temp.replace(cache)
                return video,saved
            except MediaTooLong:
                video.unlink(missing_ok=True)
                raise
            except (httpx.HTTPError,ExtractionError):
                video.unlink(missing_ok=True)
        raise ExtractionError('已取得视频信息，但公开播放地址暂时无法下载。')
