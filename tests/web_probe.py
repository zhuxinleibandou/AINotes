import json
from pathlib import Path
from backend.extract import extract
urls={
 'ordinary-web':'https://github.com/microsoft/markitdown',
 'xiaoyuzhou':'https://www.xiaoyuzhoufm.com/',
 'wechat':'https://mp.weixin.qq.com/',
}
results=[]
for label,url in urls.items():
 try:
  value=extract({'id':'probe-'+label,'title':'测试','source':{'kind':'url','content':url}},lambda:False,lambda _:None)
  results.append({'platform':label,'success':True,'title':value['title'],'segments':len(value['segments']),'scope':value['scope']})
 except Exception as exc:results.append({'platform':label,'success':False,'reason':str(exc)})
p=Path('output/verification/web-platforms.json');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps(results,ensure_ascii=False,indent=2))
