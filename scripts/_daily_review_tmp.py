import sqlite3, json, os, glob
from datetime import date

base = r'C:\Users\Administrator\.openclaw\workspace\quant-learn'

# 1. sim_trades today
db = os.path.join(base, 'data', 'sim_live_mirror.db')
if os.path.exists(db):
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print('sim tables:', cur.fetchall())
    # check schema
    cur.execute("PRAGMA table_info(sim_trades)")
    cols = cur.fetchall()
    print('sim_trades columns:', cols)
    cur.execute("SELECT * FROM sim_trades ORDER BY rowid DESC LIMIT 20")
    rows = cur.fetchall()
    print('sim_trades last 20 rows:')
    for r in rows: print(r)
    conn.close()
else:
    print('sim db NOT found at', db)

# 2. real_holdings
hpath = os.path.join(base, 'data', 'real_holdings.json')
with open(hpath) as f:
    holdings = json.load(f)
print('\n=== real_holdings ===')
print(json.dumps(holdings, indent=2, ensure_ascii=False))

# 3. reviews today
review_path = os.path.join(base, 'docs', 'reviews', '2026-05-27.md')
if os.path.exists(review_path):
    with open(review_path) as f:
        print('\n=== review today ===')
        print(f.read())
else:
    print('\nNo review file for 2026-05-27')

# 4. pm.db
pm = os.path.join(base, 'data', 'pm.db')
if os.path.exists(pm):
    conn = sqlite3.connect(pm)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print('\npm tables:', cur.fetchall())
    cur.execute("PRAGMA table_info(tasks)")
    print('tasks columns:', cur.fetchall())
    cur.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 20")
    for r in cur.fetchall(): print('task:', r)
    conn.close()
else:
    print('\npm db NOT found at', pm)
