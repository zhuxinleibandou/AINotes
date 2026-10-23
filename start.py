#!/usr/bin/env python3
"""Local Beta launcher; never stop an unknown process or open another installation."""
import hashlib
import json
import os
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
import uvicorn
from backend.version import VERSION

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8317'
os.chdir(ROOT)

def identity():
    return hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]

def server_info():
    try:
        with urllib.request.urlopen(URL+'/api/health',timeout=1) as response:
            return json.load(response)
    except Exception:
        return None

def matching(info):
    return info and info.get('name')=='拾页' and info.get('version')==VERSION and info.get('installation')==identity()

if __name__=='__main__':
    info = server_info()
    if info:
        if not matching(info):
            raise SystemExit('8317 端口已有另一版本或另一目录的服务。请关闭原服务窗口，再启动本目录的拾页。资料不会自动移动。')
        webbrowser.open(URL)
        print('拾页已经运行，已打开浏览器。')
    else:
        def open_when_ready():
            for _ in range(60):
                if matching(server_info()):
                    webbrowser.open(URL)
                    return
                time.sleep(.5)
        threading.Thread(target=open_when_ready,daemon=True).start()
        print('拾页 '+VERSION+' 正在启动。关闭此窗口会停止服务；处理中任务会保留，可下次继续。')
        uvicorn.run('backend.app:app',host='127.0.0.1',port=8317,log_level='warning')
