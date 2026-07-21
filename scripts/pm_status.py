import sqlite3
from collections import Counter

DB = "data/pm.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# Active tasks only (exclude archived)
cur.execute("SELECT id, type, title, status, priority, assigned_to, updated_at, result_notes, root_cause, work_notes FROM tasks ORDER BY priority, id")
rows = cur.fetchall()

print("=== ACTIVE TASK COUNT:", len(rows), "===")
status_counter = Counter(r[3] for r in rows)
print("STATUS BREAKDOWN:", dict(status_counter))
prio_counter = Counter(r[4] for r in rows)
print("PRIORITY BREAKDOWN:", dict(prio_counter))

print("\n=== DETAIL ===")
for r in rows:
    tid, ttype, title, status, prio, owner, updated, notes, root, work = r
    print(f"\n[{tid}] {title}")
    print(f"  status={status} | priority={prio} | owner={owner} | updated={updated}")
    if notes: print(f"  result_notes: {notes[:200]}")
    if root: print(f"  root_cause: {root[:200]}")
    if work: print(f"  work_notes: {work[-300:]}")
