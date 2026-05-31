import sqlite3, json, os
from datetime import date, datetime

base = r'C:\Users\Administrator\.openclaw\workspace\quant-learn'
db = os.path.join(base, 'data', 'sim_live_mirror.db')

conn = sqlite3.connect(db)
cur = conn.cursor()

# sim_daily_nav schema
print('=== sim_daily_nav schema ===')
cur.execute("PRAGMA table_info(sim_daily_nav)")
print(cur.fetchall())

print('\n=== sim_daily_nav latest ===')
cur.execute("SELECT * FROM sim_daily_nav ORDER BY id DESC LIMIT 10")
cols = [d[0] for d in cur.description]
print('columns:', cols)
for r in cur.fetchall(): print(r)

# threshold_state
print('\n=== threshold_state ===')
cur.execute("PRAGMA table_info(threshold_state)")
print('threshold_state columns:', cur.fetchall())
cur.execute("SELECT * FROM threshold_state ORDER BY last_triggered DESC LIMIT 20")
for r in cur.fetchall(): print(r)

# strategy_shadow_signals today
print('\n=== strategy_shadow_signals 2026-05-27 ===')
cur.execute("PRAGMA table_info(strategy_shadow_signals)")
print('columns:', cur.fetchall())
cur.execute("SELECT * FROM strategy_shadow_signals WHERE date(created_at)='2026-05-27' OR date(timestamp)='2026-05-27' LIMIT 20")
for r in cur.fetchall(): print(r)

# push_history today
print('\n=== push_history today ===')
cur.execute("SELECT * FROM push_history WHERE date(created_at)='2026-05-27' OR date(timestamp)='2026-05-27' LIMIT 20")
for r in cur.fetchall(): print(r)

# sim_trades account 2 (real_portfolio) 
print('\n=== sim_trades account 2 (real) ===')
cur.execute("SELECT * FROM sim_trades WHERE account_id=2 ORDER BY id DESC LIMIT 10")
for r in cur.fetchall(): print(r)

conn.close()
