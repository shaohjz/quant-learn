"""看今天的候选"""
import sys; sys.path.insert(0, 'scripts')
from intraday_scanner import get_universe, fetch_all_realtime, filter_universe

df = fetch_all_realtime()

# 涨幅 1-7% 成交额大的 Top10
mask = df['涨跌幅'].between(1, 7)
top = df[mask].sort_values('成交额', ascending=False).head(10)
print("=== 今日涨幅 1-7% + 成交额 Top10 ===")
for _, r in top.iterrows():
    print(f"  {r['代码']} {r['名称']:6s} 涨{r['涨跌幅']:+.1f}% 价{r['最新价']:.2f} 额{r['成交额']/1e8:.1f}亿")

print("\n=== 涨幅 3-6%（超跌反弹候选）Top10 ===")
mask2 = df['涨跌幅'].between(3, 6)
top2 = df[mask2].sort_values('成交额', ascending=False).head(10)
for _, r in top2.iterrows():
    print(f"  {r['代码']} {r['名称']:6s} 涨{r['涨跌幅']:+.1f}% 价{r['最新价']:.2f} 额{r['成交额']/1e8:.1f}亿")
