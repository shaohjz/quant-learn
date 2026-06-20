"""List all open/in_progress tasks with details from pm.db"""
import sqlite3
import json

conn = sqlite3.connect('data/pm.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get all non-done tasks
cur.execute("""
  SELECT id, type, title, status, priority, created_at, updated_at, description, work_notes
  FROM tasks
  WHERE status NOT IN ('done', 'verified', 'closed')
  ORDER BY
    CASE priority
      WHEN 'P0' THEN 1
      WHEN 'P1' THEN 2
      WHEN 'P2' THEN 3
      ELSE 4
    END,
    updated_at ASC
""")
rows = cur.fetchall()
print(f"=== {len(rows)} Active Tasks ===\n")
for r in rows:
    print(f"[{r['priority']}] {r['id']} | status={r['status']} | updated={r['updated_at'][:10]}")
    print(f"  Title: {r['title'][:80]}")
    if r['description']:
        desc = r['description'][:200].replace('\n', ' ')
        print(f"  Desc: {desc}")
    print()

conn.close()
