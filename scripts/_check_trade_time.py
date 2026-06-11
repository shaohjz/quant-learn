"""查看交易时间记录"""
import sqlite3
conn = sqlite3.connect('data/sim_live_mirror.db')
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT trade_date, trade_time, created_at, stock_code, stock_name, direction, quantity, price "
    "FROM sim_trades WHERE account_id=1 ORDER BY created_at DESC LIMIT 10"
).fetchall()

print(f"{'日期':<12} {'时间':<8} {'方向':^4} {'代码':<8} {'名称':<8} {'数量':>5} {'价格':>7}")
print("-" * 85)
for r in rows:
    d = dict(r)
    icon = "买" if d['direction'] == 'BUY' else "卖"
    t = d['trade_time'] or '(无)'
    print(f"{d['trade_date']:<12} {t:<8} {icon:^4} "
          f"{d['stock_code']:<8} {d['stock_name']:<8} {d['quantity']:>5} {d['price']:>7.3f}")

conn.close()
