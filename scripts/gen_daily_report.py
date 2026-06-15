import sqlite3
from datetime import date, datetime

db_path = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 状态统计
cur.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status")
status_stats = {r['status']: r['cnt'] for r in cur.fetchall()}

# 优先级统计
cur.execute("SELECT priority, COUNT(*) as cnt FROM tasks GROUP BY priority")
pri_stats = {r['priority']: r['cnt'] for r in cur.fetchall()}

# 类型统计
cur.execute("SELECT type, COUNT(*) as cnt FROM tasks GROUP BY type")
type_stats = {r['type']: r['cnt'] for r in cur.fetchall()}

print("=== 状态统计 ===")
for k, v in sorted(status_stats.items()):
    print(f"  {k}: {v}")

print("\n=== 优先级统计 ===")
for k, v in sorted(pri_stats.items()):
    print(f"  {k}: {v}")

print("\n=== 类型统计 ===")
for k, v in sorted(type_stats.items()):
    print(f"  {k}: {v}")

# in_progress 详情
print("\n=== IN_PROGRESS 任务详情 ===")
cur.execute("""
SELECT id, type, title, priority, assigned_to, updated_at
FROM tasks
WHERE status = 'in_progress'
ORDER BY priority DESC, id
""")
for t in cur.fetchall():
    print(f"  {t['id']} [{t['priority']}] assigned={t['assigned_to']}")
    print(f"    {t['title'][:70]}")
    print(f"    updated: {t['updated_at']}")

# open 状态
print("\n=== OPEN 任务（需分配/处理）===")
cur.execute("""
SELECT id, type, title, priority, assigned_to, created_at
FROM tasks
WHERE status = 'open'
ORDER BY priority DESC, id
""")
for t in cur.fetchall():
    print(f"  {t['id']} [{t['priority']}] {t['title'][:60]}")

# testing 状态
print("\n=== TESTING 任务（待验收）===")
cur.execute("""
SELECT id, type, title, priority, assigned_to
FROM tasks
WHERE status = 'testing'
ORDER BY priority DESC, id
""")
for t in cur.fetchall():
    print(f"  {t['id']} [{t['priority']}] assigned={t['assigned_to']} {t['title'][:60]}")

# 本周新增（2026-06-09 及之后）
print("\n=== 本周新增任务 (2026-06-09 起) ===")
cur.execute("""
SELECT id, type, title, status, priority, created_at
FROM tasks
WHERE date(created_at) >= '2026-06-09'
ORDER BY created_at DESC
""")
for t in cur.fetchall():
    print(f"  {t['id']} [{t['status']}][{t['priority']}] {t['created_at'][:10]} {t['title'][:55]}")

# 阻塞项分析：open + P0/P1
print("\n=== 阻塞/紧急项分析 ===")
cur.execute("""
SELECT id, title, priority, status, assigned_to
FROM tasks
WHERE (status = 'open' OR status = 'in_progress') AND (priority = 'P0' OR priority = 'S1')
ORDER BY priority, id
""")
for t in cur.fetchall():
    print(f"  ⚠ {t['id']} [{t['priority']}][{t['status']}] {t['title'][:60]}")

conn.close()
