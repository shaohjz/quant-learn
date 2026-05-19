import sys
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn\scripts')
from iwiki_helper import call_iwiki

for docid in [4020557278, 4020557289, 4020557311, 4020557317]:
    r = call_iwiki('renameDocumentTitle', id=docid, new_title='__可删除_测试页__')
    res = r.get('data', r)
    print(f'docid={docid}: {res}')
