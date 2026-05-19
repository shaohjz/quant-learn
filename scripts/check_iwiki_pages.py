import sys
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts')
from iwiki_helper import call_iwiki
import json

# 列出最新子页
r = call_iwiki('getSpacePageTree', parentid=4018670685)
docs = r.get('data', [])
if isinstance(docs, list):
    today_docs = [d for d in docs if 'AI' in d.get('title', '') or '5月19' in d.get('title', '')]
    print(f'找到 {len(today_docs)} 个相关子页:')
    for d in today_docs[-10:]:
        title = d.get('title', '')
        docid = d.get('docid', 0)
        print(f'  docid={docid} title={title}')
        print(f'  url: https://iwiki.woa.com/p/{docid}')
else:
    print('返回非列表:', str(r)[:500])
