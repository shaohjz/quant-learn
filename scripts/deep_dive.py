import sqlite3
from datetime import datetime, date

db = 'data/sim_live_mirror.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 深入分析 7/2 -> 7/3 NAV 跳变
print("=== 7/2 vs 7/3 NAV 分析 ===")
cur.execute("SELECT * FROM sim_daily_nav WHERE trade_date IN ('2026-07-02', '2026-07-03') ORDER BY trade_date")
for r in cur.fetchall():
    print(dict(r))

# 7/3 的交易记录
print("\n=== 7/3 所有交易 ===")
cur.execute("SELECT * FROM sim_trades WHERE trade_date = '2026-07-03' ORDER BY trade_time")
for r in cur.fetchall():
    print(dict(r))

# sim_account 的 updated_at 变化
print("\n=== sim_account 最新状态 ===")
cur.execute("SELECT * FROM sim_account")
for r in cur.fetchall():
    print(dict(r))

# 检查 7/3 的 NAV 写入是否正常
print("\n=== 7/3 NAV 详情 ===")
cur.execute("SELECT * FROM sim_daily_nav WHERE trade_date = '2026-07-03'")
r = cur.fetchone()
if r:
    print(dict(r))
else:
    print("7/3 NAV 记录不存在！")

# 检查 account_id=2 的 NAV
print("\n=== account_id=2 NAV 记录 ===")
cur.execute("SELECT * FROM sim_daily_nav WHERE account_id=2 ORDER BY trade_date DESC LIMIT 5")
for r in cur.fetchall():
    print(dict(r))

# 检查 real_portfolio 的持仓
print("\n=== real_portfolio (account_id=2) 持仓 ===")
cur.execute("SELECT * FROM sim_positions WHERE account_id=2")
for r in cur.fetchall():
    print(dict(r))

# 检查 account_events
print("\n=== sim_account_events ===")
cur.execute("SELECT * FROM sim_account_events ORDER BY created_at DESC LIMIT 10")
for r in cur.fetchall():
    print(dict(r))

conn.close()
