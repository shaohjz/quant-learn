#!/usr/bin/env python3
"""Check open tasks in pm.db"""
import sqlite3
conn = sqlite3.connect('data/pm.db')
cur = conn.cursor()

cur.execute('SELECT status, COUNT(*) FROM tasks GROUP BY status')
print('Task status:')
for r in cur.fetchall():
    print(' ', r[0], ':', r[1])

cur.execute("SELECT id, type, title, status, priority FROM tasks WHERE status='open' ORDER BY priority, id")
print()
print('Open tasks:')
for r in cur.fetchall():
    print(' ', r[0], r[1], r[2][:60], '|', r[3], '|', r[4])

conn.close()
