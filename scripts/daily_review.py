import sys, os
import sqlite3
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# REQ-095: 优先使用 sim_live_mirror.db（运行时实际使用的数据库）
# 若不存在则回退到 sim/db.py 的 get_conn()
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_LIVE = os.path.join(_PROJECT_ROOT, "data", "sim_live_mirror.db")
_DB_DEFAULT = os.path.join(_PROJECT_ROOT, "data", "sim.db")

if os.path.exists(_DB_LIVE):
    db = _DB_LIVE
elif os.path.exists(_DB_DEFAULT):
    db = _DB_DEFAULT
else:
    from sim.db import DB_PATH
    db = str(DB_PATH)

conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. 账户信息
print("=== 账户信息 ===")
cur.execute("SELECT * FROM sim_account")
accounts = cur.fetchall()
for a in accounts:
    print(dict(a))

# 2. 当前持仓
print("\n=== 当前持仓 ===")
cur.execute("SELECT * FROM sim_positions")
positions = cur.fetchall()
for p in positions:
    d = dict(p)
    print(d)

# 3. 最近交易日NAV（取最近5天）
print("\n=== 最近NAV（最近10条）===")
cur.execute("SELECT * FROM sim_daily_nav ORDER BY trade_date DESC LIMIT 10")
navs = cur.fetchall()
for n in navs:
    print(dict(n))

# 4. 今日交易（2026-07-06）
today = '2026-07-06'
print(f"\n=== 今日交易 {today} ===")
cur.execute("SELECT * FROM sim_trades WHERE trade_date = ?", (today,))
trades = cur.fetchall()
if trades:
    for t in trades:
        print(dict(t))
else:
    print("(无今日交易)")

# 5. 最近交易（最近10条）
print("\n=== 最近交易（最近10条）===")
cur.execute("SELECT * FROM sim_trades ORDER BY trade_date DESC, id DESC LIMIT 10")
recent_trades = cur.fetchall()
for t in recent_trades:
    print(dict(t))

# 6. 持仓盈亏分析 - 计算当前价格和成本价
print("\n=== 持仓盈亏分析 ===")
cur.execute("""
    SELECT sp.*, 
           (sp.current_price - sp.avg_cost) as price_diff,
           CASE WHEN sp.avg_cost > 0 THEN (sp.current_price - sp.avg_cost)/sp.avg_cost*100 ELSE 0 END as pct_change
    FROM sim_positions sp
""")
for row in cur.fetchall():
    d = dict(row)
    print(f"{d['stock_code']} {d['stock_name']}: 数量={d['quantity']} 成本={d['avg_cost']:.2f} 现价={d['current_price']:.2f} 浮盈={d['pnl']:.2f}({d['pnl_pct']:.2f}%) trailing_stop={d.get('trailing_stop_price', 'N/A')} highest={d.get('highest_price', 'N/A')}")

# 7. 检查止损/止盈触发情况
print("\n=== 止损/止盈检查 ===")
cur.execute("SELECT * FROM sim_positions WHERE trailing_stop_price IS NOT NULL")
for row in cur.fetchall():
    d = dict(row)
    cp = d['current_price']
    tsp = d['trailing_stop_price']
    if cp <= tsp:
        print(f"⚠️ {d['stock_code']} {d['stock_name']}: 当前价{cp:.2f} 已触发移动止损{tsp:.2f}！")
    else:
        print(f"✅ {d['stock_code']} {d['stock_name']}: 当前价{cp:.2f} 止损价{tsp:.2f} 距离{((cp-tsp)/cp*100):.2f}%")

conn.close()
