import sqlite3
import os

print("=== sim_live_mirror.db ===")
conn = sqlite3.connect('data/sim_live_mirror.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cursor.fetchall()]
print("Tables:", tables)
for t in tables:
    cursor.execute(f'PRAGMA table_info({t})')
    cols = [r[1] for r in cursor.fetchall()]
    print(f"  {t}: {cols}")
    cursor.execute(f'SELECT COUNT(*) FROM {t}')
    print(f"    rows: {cursor.fetchone()[0]}")
    # show sample row
    cursor.execute(f'SELECT * FROM {t} LIMIT 1')
    row = cursor.fetchone()
    if row:
        print(f"    sample: {row}")
conn.close()

print("\n=== pm.db ===")
conn2 = sqlite3.connect('data/pm.db')
cursor2 = conn2.cursor()
cursor2.execute("SELECT name FROM sqlite_master WHERE type='table'")
pm_tables = [r[0] for r in cursor2.fetchall()]
print("Tables:", pm_tables)
for t in pm_tables:
    cursor2.execute(f'PRAGMA table_info({t})')
    cols = [r[1] for r in cursor2.fetchall()]
    print(f"  {t}: {cols}")
    cursor2.execute(f'SELECT COUNT(*) FROM {t}')
    print(f"    rows: {cursor2.fetchone()[0]}")
    cursor2.execute(f'SELECT * FROM {t} LIMIT 2')
    rows = cursor2.fetchall()
    for r in rows:
        print(f"    sample: {r}")
conn2.close()
