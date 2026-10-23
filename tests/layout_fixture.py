"""Synthetic export stress fixture in an isolated database, never normal user data."""
import json
import os
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.environ['QUICKLEARN_DATA']=str(root/'output'/'verification'/'layout-library')
from backend import store
store.init()
note=store.create_note({'kind':'text','content':'仅用于长图导出与排版压力验收。'},'排版压测')
store.update_note(note['id'],segments=[{'id':'s1','location':'排版压测夹具','text':'测试输入','start':None,'end':None}],scope='合成排版测试数据，不是AI生成内容')
paragraph='这是一段中文长文本，用来检验自动换行、标点与数字 1080，以及关键字 **重点** 的排版。完整内容应当保留，不能裁掉。\n\n'
table='| 对比项目 | 条件与说明 |\n|---|---|\n| 示例甲 | 保留数字 37% 与适用条件 |\n| 示例乙 | 仅为排版压力测试 |\n\n'
content={'title':'长标题排版压力验收：中文自动换行、表格与超长单卡片分图导出','subtitle':'仅用于功能压力测试的合成数据。','overview':'验证三类布局：长标题、表格和跨页连续内容。','sections':[{'title':'超长步骤卡片','kind':'steps','markdown':paragraph*65,'keypoints':['自动换行','完整保留'],'source_ids':['s1']},{'title':'对比表格的分图边界','kind':'comparison','markdown':table*12,'keypoints':['整表保留'],'source_ids':['s1']}],'limitations':['此内容只验证排版，不包含真实学习结论。'],'conclusion':'完整保留，不裁切。'}
store.save_note_version(note['id'],content,expected=0)
(root/'output'/'verification'/'layout-note-id.txt').write_text(note['id'])
print(note['id'])
