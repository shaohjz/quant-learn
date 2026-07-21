import sqlite3, os, json
from collections import Counter, defaultdict

db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "pm.db"))
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT id,type,title,status,priority,created_at,updated_at,assigned_to,result_notes,work_notes FROM tasks ORDER BY id")
tasks = [dict(r) for r in cur.fetchall()]

# Normalize status buckets
def bucket(s):
    s = (s or "").lower()
    if s in ("todo","pending","open"): return "todo"
    if s in ("in_progress","doing","progress"): return "in_progress"
    if s in ("done","verified","fixed","closed"): return "done"
    if s in ("blocked","block"): return "blocked"
    # testing is a mid-state; count separately
    return s  # testing etc.

buckets = defaultdict(list)
for t in tasks:
    buckets[bucket(t["status"])].append(t)

print("=== STATUS DISTRIBUTION (active tasks, n=%d) ===" % len(tasks))
cnt = Counter(bucket(t["status"]) for t in tasks)
for k,v in sorted(cnt.items(), key=lambda x:-x[1]):
    print(f"  {k}: {v}")

print("\n=== TODO / PENDING ===")
for t in buckets["todo"]:
    print(f"  [{t['priority']}] {t['id']} - {t['title']}  (assigned: {t['assigned_to']})")

print("\n=== IN_PROGRESS ===")
for t in buckets["in_progress"]:
    print(f"  [{t['priority']}] {t['id']} - {t['title']}")

print("\n=== TESTING (needs verify) ===")
for t in buckets["testing"]:
    print(f"  [{t['priority']}] {t['id']} - {t['title']}  (updated: {t['updated_at']})")

print("\n=== DONE/VERIFIED ===")
for t in buckets["done"]:
    print(f"  [{t['priority']}] {t['id']} - {t['title']}")

print("\n=== BLOCKED ===")
for t in buckets["blocked"]:
    print(f"  [{t['priority']}] {t['id']} - {t['title']}")

# Priority breakdown among active non-done
print("\n=== PRIORITY x STATUS MATRIX ===")
prio_order = ["P0","high","P1","P2","P3"]
matrix = defaultdict(Counter)
for t in tasks:
    matrix[t["priority"]][bucket(t["status"])] += 1
for p in prio_order:
    if matrix[p]:
        parts = ", ".join(f"{k}={v}" for k,v in matrix[p].items())
        print(f"  {p}: {parts}")

conn.close()
