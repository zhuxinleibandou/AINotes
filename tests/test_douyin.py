import json
from pathlib import Path
import httpx
import pytest
from backend import douyin
from backend.extract import ExtractionError
from backend.codex import Cancelled

VID='7650000000000000000'  # Synthetic identifier; no personal viewing history.

def html(ident=VID):
    value={'loaderData':{'video_(id)/page':{'videoInfoRes':{'item_list':[{'aweme_id':ident,'desc':'公开视频：条件与限制','video':{'play_addr':{'url_list':['https://cdn.example.test/video.mp4']}}}]}}}}
    return 'window._ROUTER_DATA = '+json.dumps(value,ensure_ascii=False)+'; document.title="test";'

def client_for(monkeypatch,handler):
    original=httpx.Client
    monkeypatch.setattr(douyin.httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    monkeypatch.setattr(douyin,'check_url',lambda url:url)

def test_guest_session_works_without_browser_or_imported_cookies(tmp_path,monkeypatch):
    requests=[]
    def handler(request):
        requests.append(request)
        if request.url.host=='cdn.example.test':return httpx.Response(200,content=b'video bytes',headers={'content-type':'video/mp4'})
        if request.headers.get('cookie')=='ttwid=GUEST_TEST':return httpx.Response(200,text=html())
        assert 'cookie' not in request.headers
        return httpx.Response(200,text='window._ROUTER_DATA = {};',headers={'set-cookie':'ttwid=GUEST_TEST; Path=/; Secure; HttpOnly'})
    client_for(monkeypatch,handler)
    monkeypatch.setattr(douyin,'_verify',lambda path,stop:None)
    monkeypatch.setattr(douyin,'check_link_file',lambda path,stop:90)
    path,info=douyin.public_video('https://www.douyin.com/video/'+VID,tmp_path,lambda:False,lambda _:None)
    assert path.read_bytes()==b'video bytes' and info['id']==VID
    assert len(requests)==3
    assert requests[-1].headers.get('cookie') is None # visitor Cookie never sent to unrelated CDN
    cached=(tmp_path/'douyin-public.json').read_text()
    assert 'GUEST_TEST' not in cached and 'https://' not in cached
    douyin.public_video('https://www.douyin.com/video/'+VID,tmp_path,lambda:False,lambda _:None)
    assert len(requests)==3 # validated video checkpoint reused

def test_parser_requires_matching_id_and_safe_json():
    assert douyin.parse_share(html(),VID)['id']==VID
    assert douyin.parse_share(html('1'),VID) is None
    assert douyin.parse_share('window._ROUTER_DATA = alert("bad")',VID) is None
    assert douyin.parse_share('window._ROUTER_DATA = {};',VID) is None
    assert not douyin.is_douyin('https://notdouyin.com/video/'+VID)

def test_guest_page_failure_is_bounded(tmp_path,monkeypatch):
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,text='window._ROUTER_DATA = {};')
    client_for(monkeypatch,handler)
    with pytest.raises(ExtractionError,match='没有返回'):
        douyin.public_video('https://www.douyin.com/video/'+VID,tmp_path,lambda:False,lambda _:None)
    assert len(requests)==3 and not (tmp_path/'douyin-video.mp4').exists()

def test_html_download_and_cancellation_not_success(tmp_path,monkeypatch):
    def handler(request):
        if request.url.host=='cdn.example.test':return httpx.Response(200,text='<html>verify</html>')
        return httpx.Response(200,text=html())
    client_for(monkeypatch,handler)
    with pytest.raises(ExtractionError,match='无法下载'):
        douyin.public_video('https://www.douyin.com/video/'+VID,tmp_path,lambda:False,lambda _:None)
    assert not (tmp_path/'douyin-video.mp4').exists()
    with pytest.raises(Cancelled):
        douyin.public_video('https://www.douyin.com/video/'+VID,tmp_path,lambda:True,lambda _:None)
