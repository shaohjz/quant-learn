import sqlite3
db = sqlite3.connect('data/pm.db')
cur = db.execute(
    "SELECT id, title, status, priority, updated_at, assigned_to FROM tasks "
    "WHERE status IN ('pending','in_progress','testing') ORDER BY priority, updated_at"
)
rows = cur.fetchall()
for r in rows:
    print(f"{r[0]:20s} | {r[3]:5s} | {r[2]:15s} | {str(r[4] or '-'):20s} | {str(r[5] or '-'):12s} | {r[1][:50]}")
db.close()
