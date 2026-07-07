"""Query all open/pending tasks with details."""
import sqlite3

conn = sqlite3.connect("data/pm.db")
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT id, title, description, status, priority, created_at FROM tasks WHERE status IN ('open','pending') ORDER BY priority, id"
).fetchall()

for r in rows:
    print(f"\n{'='*70}")
    print(f"  {r['id']} ({r['priority']}) [{r['status']}]")
    print(f"  title: {r['title']}")
    print(f"  desc: {r['description'][:200] if r['description'] else 'N/A'}")
    print(f"  created: {r['created_at']}")

print(f"\n{'='*70}")
print(f"Total: {len(rows)} tasks")
conn.close()
