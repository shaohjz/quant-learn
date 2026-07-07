import sqlite3
from datetime import date

today = date.today().strftime('%Y-%m-%d')
conn = sqlite3.connect('data/pm.db')
c = conn.cursor()

c.execute('SELECT id, type, title, status, priority, updated_at FROM tasks WHERE updated_at LIKE ? ORDER BY updated_at', (today+'%',))
rows = c.fetchall()
print('=== 今日状态变更 ===')
for r in rows:
    print(f'{r[0]:25s} | {r[1]:10s} | {r[3]:12s} | {r[4]:5s} | {str(r[2]):50s}')

print()
# 统计当前积压
c.execute("SELECT status, COUNT(*) FROM tasks WHERE status IN ('open','pending','in_progress','fixed') GROUP BY status")
print('=== 当前积压统计 ===')
for r in c.fetchall():
    print(f'{r[0]}: {r[1]}')

print()
c.execute("SELECT id, title, priority FROM tasks WHERE status IN ('open','pending','in_progress') AND priority IN ('P0','high') ORDER BY priority")
print('=== 当前 P0 积压 ===')
for r in c.fetchall():
    print(f'{r[0]:25s} | {r[2]:5s} | {r[1]}')

conn.close()
