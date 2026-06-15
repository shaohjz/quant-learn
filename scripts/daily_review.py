import sqlite3, json, os
from datetime import datetime, timedelta

sim_db = 'data/sim.db'
pm_db = 'data/pm.db'

conn = sqlite3.connect(sim_db)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print('=== sim_daily_nav 表结构 ===')
cursor.execute("PRAGMA table_info(sim_daily_nav)")
for c in cursor.fetchall():
    print(c[1], c[2])

print('\n=== sim_trades 表结构 ===')
cursor.execute("PRAGMA table_info(sim_trades)")
for c in cursor.fetchall():
    print(c[1], c[2])

print('\n=== sim_orders 表结构 ===')
cursor.execute("PRAGMA table_info(sim_orders)")
for c in cursor.fetchall():
    print(c[1], c[2])

print('\n=== 1. sim_account 账户状态 ===')
cursor.execute("SELECT * FROM sim_account ORDER BY id DESC")
for r in cursor.fetchall():
    print(dict(r))

print('\n=== 2. sim_positions 持仓 ===')
cursor.execute("SELECT * FROM sim_positions ORDER BY id")
for r in cursor.fetchall():
    print(dict(r))

print('\n=== 3. sim_daily_nav 净值 ===')
cursor.execute("SELECT * FROM sim_daily_nav ORDER BY id DESC LIMIT 10")
for r in cursor.fetchall():
    print(dict(r))

print('\n=== 4. sim_trades 最近成交 ===')
cursor.execute("SELECT * FROM sim_trades ORDER BY id DESC LIMIT 10")
for r in cursor.fetchall():
    print(dict(r))

print('\n=== 5. sim_orders 订单 ===')
cursor.execute("SELECT * FROM sim_orders ORDER BY id DESC LIMIT 20")
for r in cursor.fetchall():
    print(dict(r))

print('\n=== 6. sim_account_events ===')
cursor.execute("PRAGMA table_info(sim_account_events)")
for c in cursor.fetchall():
    print(c[1], c[2])
cursor.execute("SELECT * FROM sim_account_events ORDER BY id DESC LIMIT 10")
for r in cursor.fetchall():
    print(dict(r))

conn.close()

print('\n=== 7. pm.db 最近 tasks ===')
conn2 = sqlite3.connect(pm_db)
conn2.row_factory = sqlite3.Row
cur2 = conn2.cursor()
cur2.execute("SELECT id, type, title, status, priority, created_at FROM tasks ORDER BY id DESC LIMIT 10")
for t in cur2.fetchall():
    print(dict(t))
conn2.close()
