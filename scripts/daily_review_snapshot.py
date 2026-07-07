import sqlite3
import os
import json
from datetime import datetime

db = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. 账户概况
cur.execute('SELECT * FROM sim_account')
accounts = cur.fetchall()
print('=== 账户概况 ===')
for acct in accounts:
    d = dict(acct)
    print(f"  账户{d['id']} ({d['account_name']}): "
          f"初始资金={d['initial_cash']:.2f}, "
          f"现金={d['cash']:.2f}, "
          f"总市值={d['total_value']:.2f}, "
          f"更新时间={d['updated_at']}")

# 2. 持仓详情
cur.execute('SELECT * FROM sim_positions ORDER BY account_id, stock_code')
positions = cur.fetchall()
print(f'\n=== 持仓详情 ({len(positions)} 只) ===')
for p in positions:
    d = dict(p)
    print(f"  账户{d['account_id']} | {d['stock_code']} {d['stock_name']} | "
          f"数量={d['quantity']} | 成本={d['avg_cost']:.2f} | "
          f"现价={d['current_price']:.2f} | 市值={d['market_value']:.2f} | "
          f"盈亏={d['pnl']:.2f}({d['pnl_pct']:.1f}%) | "
          f"追踪止损={d['trailing_stop_price']} | 最高价={d['highest_price']} | "
          f"更新={d['updated_at']}")

# 3. 最新NAV
cur.execute('SELECT * FROM sim_daily_nav ORDER BY trade_date DESC LIMIT 5')
navs = cur.fetchall()
print(f'\n=== 最近NAV ===')
for n in navs:
    d = dict(n)
    print(f"  {d['trade_date']} | 账户{d['account_id']} | "
          f"总市值={d['total_value']:.2f} | 现金={d['cash']:.2f} | "
          f"日收益={d['daily_return']} | 累计收益={d['cumulative_return']:.2f}% | "
          f"最大回撤={d['max_drawdown']:.2f}%")

# 4. 最近交易
cur.execute('SELECT * FROM sim_trades ORDER BY created_at DESC LIMIT 10')
trades = cur.fetchall()
print(f'\n=== 最近交易 ===')
for t in trades:
    d = dict(t)
    print(f"  {d['trade_date']} {d.get('trade_time', '')} | "
          f"账户{d['account_id']} | {d['direction']} {d['stock_code']} {d['stock_name']} | "
          f"价格={d['price']:.2f} | 数量={d['quantity']} | "
          f"理由={d['signal_reason']}")

# 5. threshold_state 中 armed 状态
cur.execute("SELECT * FROM threshold_state WHERE status IN ('armed', 'confirmed') ORDER BY stock_code")
armed = cur.fetchall()
print(f'\n=== 已触发未卖出 ({len(armed)} 条) ===')
for a in armed:
    d = dict(a)
    print(f"  {d['stock_code']} {d['stock_name']} | {d['rule_name']} | "
          f"状态={d['status']} | 触发价={d['first_hit_price']} | "
          f"确认价={d['close_price']} | 更新={d['updated_at']}")

conn.close()
