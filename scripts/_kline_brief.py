import akshare as ak
import sys
code = sys.argv[1] if len(sys.argv) > 1 else '603986'
df = ak.stock_zh_a_hist(symbol=code, period='daily', adjust='qfq', start_date='20260101')
df = df.tail(40)
c = df['收盘'].astype(float)
ma5 = c.rolling(5).mean().iloc[-1]
ma10 = c.rolling(10).mean().iloc[-1]
ma20 = c.rolling(20).mean().iloc[-1]
ma60 = c.rolling(60).mean().iloc[-1] if len(c) >= 60 else 0
print(f'代码 {code}')
print(f'MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f}')
print(f'近20日最高={c.tail(20).max():.2f} 最低={c.tail(20).min():.2f}')
print('=== 最近10日 ===')
for _, row in df.tail(10).iterrows():
    print(f"{row['日期']} O={row['开盘']:.2f} H={row['最高']:.2f} L={row['最低']:.2f} C={row['收盘']:.2f} 成交额={row['成交额']/1e8:.2f}亿")
