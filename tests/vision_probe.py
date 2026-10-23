"""Real vision integration: verify a number absent from the speech is recovered from frames."""
import json
import os
from pathlib import Path
project=Path(__file__).resolve().parents[1]
os.environ['QUICKLEARN_DATA']=str(project/'output'/'verification'/'vision-library')
from backend import store,worker
import shutil
store.init()
folder=project/'output'/'verification'/'media'
transcript=json.loads((folder/'transcription-result.json').read_text())
assert '37%' not in ''.join(s['text'] for s in transcript['segments'])
note=store.create_note({'kind':'file','filename':'verification.mp4','size':(folder/'verification.mp4').stat().st_size},'视觉补充验收',instructions='标题保留“视觉验收”，将语音和画面来源分开。')
target=store.DATA/'materials'/note['id']/'source';target.mkdir(parents=True)
shutil.copyfile(folder/'verification.mp4',target/'verification.mp4')
store.update_note(note['id'],segments=transcript['segments'],scope=transcript['scope'])
job=store.create_job(note['id'],'vision')
worker.process(job)
result=store.get_note(note['id'])
print('VISION_JOB',store.get_job(job['id'])['status'],store.get_job(job['id'])['error'],flush=True)
assert store.get_job(job['id'])['status']=='completed'
frame_text=''.join(s['text'] for s in result['segments'] if s['location'].startswith('画面 '))
assert '37' in frame_text and 'ZEBRA' in frame_text,frame_text
out=project/'output'/'verification'/'vision-result.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2))
print('VISION_SUCCESS: recovered ZEBRA-42 and 37 from frames, with independent source positions.',flush=True)
