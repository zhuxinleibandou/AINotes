"""Exercise native OCR and a real locally synthesized speech clip."""
import json
import subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from backend.extract import ocr, extract_file
root=Path(__file__).resolve().parents[1]
folder=root/'output'/'verification'/'media'
folder.mkdir(parents=True,exist_ok=True)
font_path='/System/Library/Fonts/STHeiti Light.ttc'
font=ImageFont.truetype(font_path,44)
image=Image.new('RGB',(1280,720),'#fff8ed')
draw=ImageDraw.Draw(image)
for i,text in enumerate(['拾页 · 图片与画面分析验收','三步流程：阅读 → 解释 → 核对','仅画面中出现的信息：ZEBRA-42','测试值 37%，仅为图中示例']):
 draw.text((65,100+i*130),text,font=font,fill='#664631')
picture=folder/'ocr-source.png';image.save(picture)
recognized=ocr(picture,lambda:False)
assert '37' in recognized and 'ZEBRA' in recognized,recognized
(folder/'ocr-result.txt').write_text(recognized)
print('OCR_SUCCESS',recognized,flush=True)
voice=root/'output'/'audio'/'verification-speech.wav'
if voice.exists():
 video=folder/'verification.mp4'
 subprocess.run(['ffmpeg','-v','error','-loop','1','-i',str(picture),'-i',str(voice),'-c:v','libx264','-tune','stillimage','-c:a','aac','-pix_fmt','yuv420p','-shortest','-y',str(video)],check=True)
 result=extract_file(video,folder,lambda:False,lambda stage:print(stage,flush=True))
 (folder/'transcription-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 text=''.join(s['text'] for s in result['segments'])
 assert '阅读' in text and '对照原文检查' in text and '第七天' in text,text
 print('TRANSCRIPTION_SUCCESS',text,flush=True)
