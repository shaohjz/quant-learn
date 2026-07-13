import sqlite3
from collections import Counter, defaultdict
from datetime import datetime

DB = "data/pm.db"
NOW = datetime(2026, 7, 8, 20, 4)  # Asia/Shanghai

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
cur = c.cursor()
cur.execute("SELECT * FROM tasks ORDER BY priority, id")
rows = cur.fetchall()

# Normalize status into canonical PM flow buckets
def bucket(s):
    s = (s or "").lower()
    if s in ("done", "verified", "fixed"):
        return "done"
    if s in ("testing",):
        return "testing"  # done-code complete, awaiting verification
    if s in ("in_progress", "pending", "claimed", "back_to_in_progress"):
        return "in_progress"
    if s in ("blocked", "stalled"):
        return "blocked"
    if s in ("todo", "open", "new"):
        return "todo"
    return "other"

buckets = Counter()
by_status = Counter()
recs = []
for r in rows:
    b = bucket(r["status"])
    buckets[b] += 1
    by_status[r["status"]] += 1
    recs.append(dict(r))

print("=== CANONICAL BUCKETS ===")
for k in ["todo", "in_progress", "testing", "blocked", "done", "other"]:
    print(f"{k}: {buckets.get(k,0)}")
print("TOTAL:", len(recs))
print("\n=== RAW STATUS ===")
for k, v in sorted(by_status.items()):
    print(f"{k}: {v}")

# active = not done
active = [r for r in recs if bucket(r["status"]) != "done"]
print("\n=== ACTIVE TASKS (not done) ===")
for r in sorted(active, key=lambda x: (x["priority"], x["id"])):
    print(f"{r['id']} [{r['status']}] {r['priority']} {r['title']} @{(r['assigned_to'] or '-')}")

# blocked / test-agent stuck
print("\n=== STUCK / NEEDS ATTENTION ===")
for r in active:
    notes = r["work_notes"] or ""
    if ("failed" in notes.lower()) or r["status"] == "pending" or r["status"] == "blocked":
        print(f"{r['id']} [{r['status']}] {r['priority']} assign={r['assigned_to']} updated={r['updated_at']}")
        print("   notes:", (r["result_notes"] or r["work_notes"] or "")[:300].replace("\n", " "))

c.close()
