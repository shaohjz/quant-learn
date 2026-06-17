import sys
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn\skills\a-stock-data-signals')
from a_stock_data_signals import hot_stocks_signal, northbound_signal, industry_rotation_signal

# 行业轮动
print("=== 行业轮动 ===")
ind = industry_rotation_signal(5)
print(f"共{ind['total']}个行业")
for r in ind.get("top", [])[:5]:
    print(f"  {r['name']}: {r['change_pct']}%")

print()
print("=== 北向资金 ===")
nb = northbound_signal()
print(f"方向: {nb.get('direction', 'N/A')}")
print(f"沪:{nb.get('hgt_total', 0)}亿 深:{nb.get('sgt_total', 0)}亿 合计:{nb.get('hgt_sgt_total', 0)}亿")

print()
print("=== 强势股 ===")
hs = hot_stocks_signal(top_n=5)
print(f"共{hs['total']}只")
for s in hs.get("stocks", [])[:5]:
    print(f"  {s['code']} {s['name']}: {s['change_pct']:+.2f}% | {s.get('reason', '')}")
print(f"题材热度: {hs.get('top_tags', [])[:5]}")
