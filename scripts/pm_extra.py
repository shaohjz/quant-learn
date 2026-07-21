import sqlite3
conn = sqlite3.connect('data/pm.db')
cur = conn.cursor()
cur.execute('SELECT status, priority, COUNT(*) FROM tasks GROUP BY status, priority ORDER BY status, priority')
print("=== by status/priority ===")
for r in cur.fetchall():
    print(r)
print("\n=== by owner ===")
cur.execute('SELECT assigned_to, COUNT(*) FROM tasks GROUP BY assigned_to ORDER BY COUNT(*) DESC')
for r in cur.fetchall():
    print(r)
print("\n=== updated since 2026-07-09 (recent) ===")
cur.execute("SELECT id, status, updated_at FROM tasks WHERE updated_at >= '2026-07-09' ORDER BY updated_at DESC")
for r in cur.fetchall():
    print(r)
print("\n=== archived recent ===")
cur.execute("SELECT id, status, archived_at FROM tasks_archive ORDER BY archived_at DESC LIMIT 10")
for r in cur.fetchall():
    print(r)
