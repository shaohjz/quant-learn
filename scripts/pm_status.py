import sqlite3
from collections import Counter, defaultdict
from datetime import datetime

DB = "data/pm.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute("SELECT * FROM tasks ORDER BY id")
rows = [dict(r) for r in cur.fetchall()]

print("TOTAL tasks:", len(rows))
status_counts = Counter(r['status'] for r in rows)
print("\n=== STATUS COUNTS ===")
for s, c in sorted(status_counts.items()):
    print(f"  {s:10s}: {c}")

type_counts = Counter(r['type'] for r in rows)
print("\n=== TYPE COUNTS ===")
for t, c in type_counts.items():
    print(f"  {t:6s}: {c}")

# Normalize "open" statuses: todo + pending, in_progress(claimed/in_progress/doing), testing, blocked, done/verified
open_states = ['todo', 'pending', 'backlog']
active_states = ['in_progress', 'doing', 'claimed', 'open']
testing_states = ['testing']
blocked_states = ['blocked']
closed_states = ['done', 'verified', 'closed']

def bucket(st):
    if st in open_states: return 'todo/pending'
    if st in active_states: return 'in_progress'
    if st in testing_states: return 'testing'
    if st in blocked_states: return 'blocked'
    if st in closed_states: return 'done/verified'
    return f'other:{st}'

print("\n=== BUCKET COUNTS ===")
buckets = Counter(bucket(r['status']) for r in rows)
for b, c in buckets.items():
    print(f"  {b:16s}: {c}")

# Open / active / testing / blocked tasks detail (the things PM needs to act on)
print("\n=== ACTIONABLE TASKS (not done/verified) ===")
for r in rows:
    b = bucket(r['status'])
    if b in ('done/verified',):
        continue
    print(f"  [{r['id']}] {r['status']:10s} {r['priority']:4s} assigned={r['assigned_to']}  {r['title']}")

# Blocked specifically
print("\n=== BLOCKED ===")
blocked = [r for r in rows if r['status']=='blocked']
print("count:", len(blocked))
for r in blocked:
    print(f"  [{r['id']}] {r['title']} | notes={r['work_notes']}")

# Stale in_progress/testing (updated > 7 days ago) — potential silent blockers
now = datetime(2026,7,7,20,9)
print("\n=== POTENTIAL STALE (in_progress/testing/pending, no update in >10 days) ===")
for r in rows:
    st = r['status']
    if st in ('in_progress','doing','claimed','testing','pending') and r['updated_at']:
        try:
            ut = datetime.strptime(r['updated_at'][:19], "%Y-%m-%d %H:%M:%S")
            age = (now - ut).days
            if age > 10:
                print(f"  [{r['id']}] {st:10s} updated {r['updated_at']} ({age}d ago) assigned={r['assigned_to']}  {r['title']}")
        except Exception as e:
            pass

con.close()
