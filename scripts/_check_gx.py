import sqlite3
conn = sqlite3.connect('data/sim_live_mirror.db')
conn.row_factory = sqlite3.Row

# 先看 sim_trades 表结构
print("=== sim_trades 表结构 ===")
cols = conn.execute("PRAGMA table_info(sim_trades)").fetchall()
for c in cols:
    print(f"  {c['name']} ({c['type']})")

print("\n=== 广西能源 600310 交易历史 ===")
rows = conn.execute(
    "SELECT * FROM sim_trades WHERE stock_code='600310' ORDER BY created_at"
).fetchall()
for r in rows:
    d = dict(r)
    print(f"  {d.get('trade_date')} {d.get('trade_time','-')} {d.get('direction')} {d.get('quantity')}股 @{d.get('price',0):.3f} signal={d.get('signal_type','')} trigger={d.get('trigger_rule','')}")

print(f"\n=== 最近15条交易 ===")
rows2 = conn.execute("SELECT trade_date, trade_time, stock_code, stock_name, direction, price, quantity FROM sim_trades ORDER BY created_at DESC LIMIT 15").fetchall()
for r in rows2:
    print(f"  {r['trade_date']} {r['trade_time'] or 'N/A':8s} {r['direction']:4s} {r['stock_code']} {r['stock_name']:8s} {r['quantity']}@{r['price']:.2f}")

conn.close()
