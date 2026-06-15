import sqlite3, json, os
from datetime import datetime, timedelta

sim_db = 'data/sim.db'
pm_db = 'data/pm.db'

conn = sqlite3.connect(sim_db)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

today = datetime.now().strftime('%Y-%m-%d')
print(f'=== 今日: {today} (周六，A股休市) ===\n')

print('=== 1. sim_account 账户状态 ===')
cursor.execute("SELECT * FROM sim_account ORDER BY id DESC")
for r in cursor.fetchall():
    d = dict(r)
    print(f"  账户ID: {d['id']}")
    print(f"  初始资金: {d['initial_cash']}")
    print(f"  可用资金: {d['cash']}")
    print(f"  总市值: {d['total_value']}")
    print(f"  更新时间: {d['updated_at']}")

print('\n=== 2. sim_positions 持仓明细 ===')
cursor.execute("SELECT * FROM sim_positions ORDER BY id")
positions = cursor.fetchall()
if not positions:
    print('  (无持仓)')
else:
    total_market_value = 0
    total_pnl = 0
    for r in positions:
        d = dict(r)
        total_market_value += d['market_value'] or 0
        total_pnl += d['pnl'] or 0
        print(f"  股票: {d['stock_code']}({d['stock_name']})")
        print(f"    数量: {d['quantity']} 股")
        print(f"    成本价: {d['avg_cost']}, 现价: {d['current_price']}")
        print(f"    市值: {d['market_value']}, 盈亏: {d['pnl']} ({d['pnl_pct']*100:.1f}%)")
        print(f"    追踪止损价: {d['trailing_stop_price']}")
        print(f"    更新时间: {d['updated_at']}")
        print()
    print(f"  持仓总市值: {total_market_value}")
    print(f"  持仓总盈亏: {total_pnl}")

print('\n=== 3. sim_daily_nav 净值记录 ===')
cursor.execute("SELECT COUNT(*) as cnt FROM sim_daily_nav")
cnt = cursor.fetchone()['cnt']
print(f'  记录数: {cnt}')
if cnt == 0:
    print('  ⚠️ 净值表为空！没有每日净值记录！')

print('\n=== 4. sim_trades 成交记录 ===')
cursor.execute("SELECT COUNT(*) as cnt FROM sim_trades")
cnt = cursor.fetchone()['cnt']
print(f'  记录数: {cnt}')
if cnt == 0:
    print('  ⚠️ 成交表为空！没有交易记录！')

print('\n=== 5. 最近 sim_account_events ===')
cursor.execute("SELECT * FROM sim_account_events ORDER BY id DESC LIMIT 5")
events = cursor.fetchall()
if events:
    for e in events:
        print(dict(e))
else:
    print('  (无账户事件)')

conn.close()

print('\n=== 6. pm.db OPEN 状态 tasks ===')
conn2 = sqlite3.connect(pm_db)
conn2.row_factory = sqlite3.Row
cur2 = conn2.cursor()
cur2.execute("SELECT id, type, title, status, priority, created_at FROM tasks WHERE status != 'done' ORDER BY priority, id DESC")
open_tasks = cur2.fetchall()
print(f'  未关闭 tasks: {len(open_tasks)} 条')
for t in open_tasks:
    print(f"  {t['id']} [{t['priority']}] {t['title'][:60]} - {t['status']}")

conn2.close()

print('\n=== 7. 数据质量检查 ===')
# 检查 updated_at 是否最新
conn3 = sqlite3.connect(sim_db)
conn3.row_factory = sqlite3.Row
cur3 = conn3.cursor()
cur3.execute("SELECT MAX(updated_at) as latest FROM sim_positions")
latest = cur3.fetchone()['latest']
print(f'  sim_positions 最新更新: {latest}')
print(f'  当前时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
conn3.close()
