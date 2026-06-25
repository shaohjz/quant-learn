import sqlite3
import os

# PM DB
pm_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'pm.db')
conn = sqlite3.connect(pm_path)
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = c.fetchall()
print('=== PM DB Tables ===')
for t in tables:
    print(t[0])

c.execute('PRAGMA table_info(tasks)')
print('\n=== tasks schema ===')
for row in c.fetchall():
    print(row)

c.execute('SELECT * FROM tasks')
print('\n=== tasks rows ===')
for row in c.fetchall():
    print(row)
conn.close()

# SIM DB
sim_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'sim_live_mirror.db')
conn2 = sqlite3.connect(sim_path)
c2 = conn2.cursor()
c2.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables2 = c2.fetchall()
print('\n=== SIM DB Tables ===')
for t in tables2:
    print(t[0])

tbls = ['sim_accounts','sim_positions','sim_daily_nav','sim_orders','sim_account_events']
for tbl in tbls:
    try:
        c2.execute(f"SELECT COUNT(*) FROM {tbl}")
        print(f'{tbl}: {c2.fetchone()[0]} rows')
    except:
        print(f'{tbl}: NOT FOUND')

conn2.close()
