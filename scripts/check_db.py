#!/usr/bin/env python3
import sqlite3

db_path = 'data/sim_live_mirror.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 检查有哪些表
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = c.fetchall()
print('Tables:')
for t in tables:
    print('  ', t[0])

# 检查 sim_account 内容
c.execute('SELECT * FROM sim_account')
cols = [desc[0] for desc in c.description]
print('\nsim_account columns:', cols)
for row in c.fetchall():
    print('  ', dict(row))

conn.close()
print('\nDone')
