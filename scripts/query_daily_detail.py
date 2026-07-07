import sqlite3
from datetime import date

today = date.today().strftime('%Y-%m-%d')
conn = sqlite3.connect('data/pm.db')
c = conn.cursor()

# 今日状态变更为 verified/done/fixed 的任务（完成的）
c.execute("""
SELECT id, type, title, status, priority, updated_at
FROM tasks
WHERE DATE(updated_at) = ?
  AND status IN ('verified','done','fixed')
ORDER BY updated_at
""", (today,))
rows = c.fetchall()
print('=== 今日完成（verified/done/fixed）===')
for r in rows:
    print(f'  [{r[1]}] {r[0]} | {r[3]} | {r[4]} | {r[2]}')

print()

# 今日新建的任务
c.execute("""
SELECT id, type, title, status, priority, created_at
FROM tasks
WHERE DATE(created_at) = ?
ORDER BY created_at
""", (today,))
rows = c.fetchall()
print('=== 今日新建 ===')
for r in rows:
    print(f'  [{r[1]}] {r[0]} | {r[3]} | {r[4]} | {r[2]}')

print()

# 当前 open/pending/in_progress 按优先级统计
c.execute("""
SELECT priority, COUNT(*) as cnt
FROM tasks
WHERE status IN ('open','pending','in_progress')
GROUP BY priority
ORDER BY
  CASE priority
    WHEN 'P0' THEN 1
    WHEN 'high' THEN 2
    WHEN 'P1' THEN 3
    WHEN 'P2' THEN 4
    WHEN 'medium' THEN 5
    ELSE 6
  END
""")
print('=== 积压按优先级 ===')
for r in c.fetchall():
    print(f'  {r[0]}: {r[1]}')

print()

# 当前 open/pending/in_progress 按状态统计
c.execute("""
SELECT status, COUNT(*) as cnt
FROM tasks
WHERE status IN ('open','pending','in_progress')
GROUP BY status
""")
print('=== 积压按状态 ===')
for r in c.fetchall():
    print(f'  {r[0]}: {r[1]}')

conn.close()
