import sqlite3
conn = sqlite3.connect('data/pm.db')
print("=== testing/fixed 状态任务 ===")
cur = conn.execute("SELECT id, title, status, priority, updated_at FROM tasks WHERE status IN ('testing','fixed') ORDER BY updated_at DESC")
rows = cur.fetchall()
if not rows:
    print("（无）")
else:
    for r in rows:
        print(r)

print("\n=== in_progress 任务 ===")
cur = conn.execute("SELECT id, title, status, priority, updated_at FROM tasks WHERE status='in_progress' ORDER BY updated_at DESC")
for r in cur.fetchall():
    print(r)

print("\n=== pending 任务（前10个）===")
cur = conn.execute("SELECT id, title, priority, updated_at FROM tasks WHERE status='pending' ORDER BY updated_at DESC LIMIT 10")
for r in cur.fetchall():
    print(r)

print("\n=== Bug 状态分布 ===")
cur = conn.execute("SELECT status, COUNT(*) FROM tasks WHERE id LIKE 'BUG-%' GROUP BY status")
for r in cur.fetchall():
    print(r)
