"""Read-only platform feasibility checks. Does not generate notes."""
import concurrent.futures
import json
import os
import subprocess
import sys
from pathlib import Path
from backend.extract import normalize_url
urls = {
 'youtube':'https://www.youtube.com/watch?v=jNQXAC9IVRw',
 'bilibili':'https://www.bilibili.com/video/av170001/',
}
if os.environ.get('AINOTES_DOUYIN_TEST_URL'):
 urls['douyin']=os.environ['AINOTES_DOUYIN_TEST_URL']
def probe(item):
 name,url=item
 try:
  result=subprocess.run([sys.executable,'-m','yt_dlp','--ignore-config','--skip-download','--no-playlist','--socket-timeout','10','--retries','0','--dump-single-json',normalize_url(url)],capture_output=True,timeout=45)
  if result.returncode==0:
   value=json.loads(result.stdout)
   return dict(platform=name,success=True,title=value.get('title'),subtitles=list((value.get('subtitles')or{})),automatic_captions=list((value.get('automatic_captions')or{})),duration=value.get('duration'))
  return dict(platform=name,success=False,reason=result.stderr.decode(errors='replace')[-1800:])
 except subprocess.TimeoutExpired:
  return dict(platform=name,success=False,reason='45秒超时')
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 results=list(pool.map(probe,urls.items()))
path=Path('output/verification/platforms.json');path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps(results,ensure_ascii=False,indent=2))
for result in results:print(json.dumps(result,ensure_ascii=False))
