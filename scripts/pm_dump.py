import sqlite3
from collections import Counter

DB = "data/pm.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# All tasks
cur.execute("SELECT * FROM tasks ORDER BY priority, status, updated_at")
rows = cur.fetchall()

status_counts = Counter()
priority_counts = Counter()
type_counts = Counter()

print(f"TOTAL ACTIVE TASKS: {len(rows)}\n")

for r in rows:
    d = dict(r)
    status_counts[d['status']] += 1
    priority_counts[d['priority']] += 1
    type_counts[d['type']] += 1

print("STATUS COUNTS:", dict(status_counts))
print("PRIORITY COUNTS:", dict(priority_counts))
print("TYPE COUNTS:", dict(type_counts))

print("\n=== FULL TASK LIST ===")
for r in rows:
    d = dict(r)
    print(f"\n[{d['id']}] {d['title']}")
    print(f"  type={d['type']} | status={d['status']} | priority={d['priority']} | assigned={d['assigned_to']}")
    print(f"  created={d['created_at']} | updated={d['updated_at']}")
    if d['description']:
        print(f"  desc={d['description'][:200]}")
    if d['status'] == 'blocked':
        print(f"  ROOT_CAUSE={d['root_cause']}")
        print(f"  WORK_NOTES={d['work_notes']}")
    if d['result_notes']:
        print(f"  result_notes={d['result_notes'][:200]}")

# freshness alerts
print("\n=== FRESHNESS ALERTS (last 4) ===")
cur.execute("SELECT * FROM freshness_alerts ORDER BY check_time DESC LIMIT 10")
for r in cur.fetchall():
    d = dict(r)
    print(f"  {d['check_time']} | source={d['source']} | ok={d['ok']} | age_h={d['age_hours']} | msg={d['message']}")

conn.close()
