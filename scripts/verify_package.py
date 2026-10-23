"""Verify a clean unpack, locked dependencies, empty library, startup and UI assets."""
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
archive=max((ROOT/'release').glob('*.zip'),key=lambda p:p.stat().st_mtime)
with tempfile.TemporaryDirectory(prefix='shiye-beta-check-') as temp:
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        assert not any(any(b in p.split('/') for b in ['data','secrets','.venv','node_modules','output']) for p in names)
        z.extractall(temp)
    project=next(Path(temp).iterdir())
    manifest=json.loads((project/'MANIFEST.sha256.json').read_text())
    for name,digest in manifest.items():
        assert hashlib.sha256((project/name).read_bytes()).hexdigest()==digest,name
    subprocess.run(['zsh','-n',str(project/'启动拾页.command')],check=True)
    subprocess.run(['uv','sync','--python','3.12','--locked'],cwd=project,check=True,capture_output=True,timeout=300)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=os.environ.copy();env.pop('QUICKLEARN_DATA',None)
    proc=subprocess.Popen([str(project/'.venv/bin/python'),'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port),'--log-level','warning'],cwd=project,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            if proc.poll() is not None:raise RuntimeError(proc.communicate()[1].decode())
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=.5) as r:health=json.load(r)
                break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('启动超时')
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/notes') as r:assert json.load(r)==[]
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/') as r:assert '拾页' in r.read().decode()
        result={'package':archive.name,'health':health,'manifest_files':len(manifest),'clean_library':True,'locked_install':True,'startup':True,'frontend':True}
        path=ROOT/'output/verification/package-check.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        proc.terminate()
        try:proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:proc.kill();proc.communicate()
