import sqlite3, json, os
from datetime import date, datetime

base = r'C:\Users\Administrator\.openclaw\workspace\quant-learn'
db = os.path.join(base, 'data', 'sim_live_mirror.db')

conn = sqlite3.connect(db)
cur = conn.cursor()

# sim_account
print('=== sim_account ===')
cur.execute("SELECT * FROM sim_account")
for r in cur.fetchall(): print(r)

# sim_positions (open positions)
print('\n=== sim_positions (open) ===')
cur.execute("SELECT * FROM sim_positions")
cols = [d[0] for d in cur.description]
print('columns:', cols)
for r in cur.fetchall(): print(r)

# sim_daily_nav latest
print('\n=== sim_daily_nav latest ===')
cur.execute("SELECT * FROM sim_daily_nav ORDER BY date DESC LIMIT 10")
for r in cur.fetchall(): print(r)

# threshold_state
print('\n=== threshold_state ===')
cur.execute("SELECT * FROM threshold_state ORDER BY last_triggered DESC LIMIT 20")
for r in cur.fetchall(): print(r)

# strategy_shadow_signals today
print('\n=== strategy_shadow_signals today ===')
cur.execute("SELECT * FROM strategy_shadow_signals WHERE date(created_at)='2026-05-27' ORDER BY created_at DESC LIMIT 20")
for r in cur.fetchall(): print(r)

# review_reflections
print('\n=== review_reflections latest ===')
cur.execute("SELECT * FROM review_reflections ORDER BY id DESC LIMIT 10")
for r in cur.fetchall(): print(r)

# daily_snapshot today
print('\n=== daily_snapshot today ===')
cur.execute("SELECT * FROM daily_snapshot WHERE date(timestamp)='2026-05-27' ORDER BY timestamp DESC LIMIT 10")
for r in cur.fetchall(): print(r)

conn.close()

# Also check real holdings more carefully
print('\n=== real_holdings.json full ===')
with open(os.path.join(base, 'data', 'real_holdings.json')) as f:
    holdings = json.load(f)
print(json.dumps(holdings, indent=2, ensure_ascii=False))
