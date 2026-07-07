"""Query tasks from pm.db by status."""
import sqlite3
import sys

status = sys.argv[1] if len(sys.argv) > 1 else "fixed"
conn = sqlite3.connect("data/pm.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT id, title, description, status, priority, created_at FROM tasks WHERE status=? ORDER BY priority",
    (status,)
).fetchall()

for r in rows:
    print(f"\n=== {r['id']} ({r['priority']}) [{r['status']}] ===")
    print(f"title: {r['title']}")
    print(f"desc: {r['description']}")
    print(f"created: {r['created_at']}")

conn.close()
