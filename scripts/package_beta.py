"""Create a source + built UI Beta archive from an explicit, private-data-free allowlist."""
import hashlib
import json
import stat
import zipfile
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.version import VERSION

FILES=['LICENSE','CONTRIBUTING.md','THIRD_PARTY_NOTICES.md','README.md','DESIGN.md','VERIFICATION.md','BETA.md','pyproject.toml','uv.lock','start.py','启动拾页.command',
       'frontend/package.json','frontend/package-lock.json','frontend/tsconfig.json','frontend/vite.config.ts','frontend/index.html']
FOLDERS=['backend','frontend/src','frontend/dist','tests','scripts']
paths=[ROOT/name for name in FILES]
for folder in FOLDERS:
    paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc','.tsbuildinfo'))
paths=sorted(set(paths))
assert all(p.is_file() for p in paths),'发布文件缺失'
manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
out=ROOT/'release';out.mkdir(exist_ok=True)
name=f'shiye-{VERSION}-mac-arm64'
archive=out/(name+'.zip')
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in paths:
        rel=p.relative_to(ROOT)
        entry=zipfile.ZipInfo(name+'/'+str(rel),date_time=(2026,10,22,0,0,0))
        entry.external_attr=(stat.S_IFREG | (0o755 if p.name.endswith('.command') else 0o644)) << 16
        entry.compress_type=zipfile.ZIP_DEFLATED
        z.writestr(entry,p.read_bytes())
    z.writestr(name+'/MANIFEST.sha256.json',json.dumps(manifest,ensure_ascii=False,indent=2))
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
(out/(name+'.sha256')).write_text(digest+'  '+archive.name+'\n')
print(json.dumps({'archive':str(archive),'files':len(paths),'bytes':archive.stat().st_size,'sha256':digest},ensure_ascii=False,indent=2))
