import sqlite3
conn = sqlite3.connect('data/pm.db')
cur = conn.cursor()
cur.execute("SELECT id, type, title, status, priority FROM tasks WHERE type='bug' AND status NOT IN ('done','fixed','verified','deployed') ORDER BY priority")
rows = cur.fetchall()
for r in rows:
    print(f"  {r[0]:12s} [{r[3]:2s}] [{r[4]:15s}] {r[2][:80]}")
print(f"---\nActive bugs not resolved: {len(rows)}")

# Check for BUG-019 detail
cur.execute("SELECT id, status, title, work_notes, updated_at FROM tasks WHERE id='BUG-019'")
r = cur.fetchone()
if r:
    print(f"\nBUG-019 detail: status={r[1]}, updated={r[4]}")
    print(f"  title: {r[2]}")
    if r[3]:
        print(f"  notes: {r[3][:200]}")

conn.close()
