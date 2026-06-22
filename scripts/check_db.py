import sqlite3, os

db = 'data/sim_live_mirror.db'
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cur.fetchall()
print('sim_live_mirror tables:', tables)
for t in tables:
    tname = t[0]
    cur.execute(f'SELECT * FROM "{tname}" LIMIT 1')
    cols = [d[0] for d in cur.description]
    print(f'  {tname}: {cols}')
    cur.execute(f'SELECT COUNT(*) FROM "{tname}"')
    print(f'    rows: {cur.fetchone()[0]}')
conn.close()

db2 = 'data/pm.db'
conn2 = sqlite3.connect(db2)
cur2 = conn2.cursor()
cur2.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables2 = cur2.fetchall()
print('pm.db tables:', tables2)
for t in tables2:
    tname = t[0]
    cur2.execute(f'SELECT * FROM "{tname}" LIMIT 1')
    cols = [d[0] for d in cur2.description]
    print(f'  {tname}: {cols}')
    cur2.execute(f'SELECT COUNT(*) FROM "{tname}"')
    print(f'    rows: {cur2.fetchone()[0]}')
conn2.close()
