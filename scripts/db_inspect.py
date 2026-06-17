import sqlite3, os

sim_db = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'
pm_db = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db'

print('=== sim_live_mirror.db ===')
if os.path.exists(sim_db):
    conn = sqlite3.connect(sim_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print('Tables:', tables)
    for (t,) in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {t}')
        cnt = cursor.fetchone()[0]
        print(f'  {t}: {cnt} rows')
        cursor.execute(f'PRAGMA table_info({t})')
        cols = [c[1] for c in cursor.fetchall()]
        print(f'    columns: {cols}')
        cursor.execute(f'SELECT * FROM {t} ORDER BY rowid DESC LIMIT 3')
        rows = cursor.fetchall()
        for r in rows:
            print(f'    {r}')
    conn.close()
else:
    print('File not found:', sim_db)

print()
print('=== pm.db ===')
if os.path.exists(pm_db):
    conn = sqlite3.connect(pm_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print('Tables:', tables)
    for (t,) in tables:
        cursor.execute(f'SELECT COUNT(*) FROM {t}')
        cnt = cursor.fetchone()[0]
        print(f'  {t}: {cnt} rows')
        cursor.execute(f'PRAGMA table_info({t})')
        cols = [c[1] for c in cursor.fetchall()]
        print(f'    columns: {cols}')
        cursor.execute(f'SELECT * FROM {t} ORDER BY rowid DESC LIMIT 3')
        rows = cursor.fetchall()
        for r in rows:
            print(f'    {r}')
    conn.close()
else:
    print('File not found:', pm_db)
