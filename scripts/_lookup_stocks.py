"""Quick stock lookup via Sina API."""
import requests, re

# 禾盛新材 002290, 莲花控股 600186, 宏和科技 603256
codes = {'sh600186': '莲花控股', 'sz002290': '禾盛新材', 'sh603256': '宏和科技'}
url = 'https://hq.sinajs.cn/list=' + ','.join(codes.keys())
headers = {'Referer': 'https://finance.sina.com.cn'}
r = requests.get(url, headers=headers, timeout=10)
r.encoding = 'gbk'
for line in r.text.strip().split('\n'):
    m = re.search(r'hq_str_(s[hz]\d+)="(.+?)"', line)
    if m:
        code = m.group(1)
        parts = m.group(2).split(',')
        name = parts[0]
        open_ = parts[1]
        yclose = parts[2]
        price = parts[3]
        high = parts[4]
        low = parts[5]
        pct = (float(price) - float(yclose)) / float(yclose) * 100 if float(yclose) > 0 else 0
        print(f'{code} {name:8s} 现价:{price} 昨收:{yclose} 涨跌:{pct:+.2f}% 开:{open_} 高:{high} 低:{low}')
