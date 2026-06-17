import sqlite3, os, json
from datetime import datetime, date

sim_db = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'
sim_db2 = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim.db'
pm_db = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db'

print('=== sim_live_mirror.db (restored from backup) ===')
if os.path.exists(sim_db):
    conn = sqlite3.connect(sim_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    print('Tables:', tables)
    for t in tables:
        cursor.execute(f'SELECT COUNT(*) as cnt FROM {t}')
        cnt = cursor.fetchone()['cnt']
        print(f'\n  Table: {t} ({cnt} rows)')
        cursor.execute(f'PRAGMA table_info({t})')
        cols = [c[1] for c in cursor.fetchall()]
        print(f'    columns: {cols}')
        cursor.execute(f'SELECT * FROM {t} ORDER BY rowid DESC LIMIT 5')
        rows = cursor.fetchall()
        for r in rows:
            print(f'    {dict(r)}')
    conn.close()
else:
    print('File not found:', sim_db)

print('\n=== sim.db ===')
if os.path.exists(sim_db2):
    conn = sqlite3.connect(sim_db2)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    print('Tables:', tables)
    for t in tables:
        cursor.execute(f'SELECT COUNT(*) as cnt FROM {t}')
        cnt = cursor.fetchone()['cnt']
        print(f'\n  Table: {t} ({cnt} rows)')
        cursor.execute(f'PRAGMA table_info({t})')
        cols = [c[1] for c in cursor.fetchall()]
        print(f'    columns: {cols}')
        cursor.execute(f'SELECT * FROM {t} ORDER BY rowid DESC LIMIT 5')
        rows = cursor.fetchall()
        for r in rows:
            print(f'    {dict(r)}')
    conn.close()
else:
    print('File not found:', sim_db2)

print('\n=== pm.db - recent tasks ===')
conn = sqlite3.connect(pm_db)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 10")
rows = cursor.fetchall()
for r in rows:
    print(dict(r))
conn.close()

# Check config for sim account settings
print('\n=== config.yaml ===')
config_path = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\config.yaml'
if os.path.exists(config_path):
    with open(config_path) as f:
        print(f.read()[:3000])
