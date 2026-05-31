import sqlite3

db_path = 'C:/Users/Administrator/.openclaw/workspace/quant-learn/data/pm.db'
conn = sqlite3.connect(db_path)

print("=== Status 分布 ===")
for row in conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status"):
    print(row)

print("\n=== testing/fixed 状态任务 ===")
for row in conn.execute("SELECT id, title, status, priority, updated_at FROM tasks WHERE status IN ('testing','fixed') ORDER BY updated_at DESC"):
    print(row)

print("\n=== in_progress 任务 ===")
for row in conn.execute("SELECT id, title, status, priority, updated_at FROM tasks WHERE status='in_progress' ORDER BY updated_at DESC"):
    print(row)

print("\n=== pending 任务（最近10个）===")
for row in conn.execute("SELECT id, title, priority, updated_at FROM tasks WHERE status='pending' ORDER BY updated_at DESC LIMIT 10"):
    print(row)

print("\n=== Bug 状态分布 (id LIKE BUG-%) ===")
for row in conn.execute("SELECT status, COUNT(*) FROM tasks WHERE id LIKE 'BUG-%' GROUP BY status"):
    print(row)

print("\n=== 最新更新任务（最近5个）===")
for row in conn.execute("SELECT id, status, updated_at FROM tasks ORDER BY updated_at DESC LIMIT 5"):
    print(row)
