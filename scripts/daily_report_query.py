"""Daily report query script for PM manager."""
import sqlite3
import os

PM_DB = os.path.join(os.path.dirname(__file__), '..', 'data', 'pm.db')

conn = sqlite3.connect(PM_DB)
cur = conn.cursor()

print("=" * 80)
print("TASK STATUS SUMMARY")
print("=" * 80)
cur.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status ORDER BY COUNT(*) DESC")
for row in cur.fetchall():
    print(f"  {row[0]:15s} {row[1]}")

print()
print("=" * 80)
print("ACTIVE TASKS (in_progress / testing / pending)")
print("=" * 80)
cur.execute("""SELECT id, type, title, status, priority, assigned_to, updated_at 
               FROM tasks 
               WHERE status IN ('in_progress','testing','pending') 
               ORDER BY status, priority, updated_at DESC""")
for r in cur.fetchall():
    print(f"  {r[0]:12s} {r[1]:6s} [{r[4]:2s}] {r[3]:20s} {r[2][:60]}")
    if r[5]:
        print(f"  {'':12s} {'':6s} {'':4s} {'':20s}  assigned: {r[5]}")
    print(f"  {'':12s} {'':6s} {'':4s} {'':20s}  updated: {r[6]}")

print()
print("=" * 80)
print("RECENTLY COMPLETED TASKS (done / fixed / verified / deployed)")
print("=" * 80)
cur.execute("""SELECT id, type, title, status, updated_at 
               FROM tasks 
               WHERE status IN ('done','fixed','verified','deployed') 
               ORDER BY updated_at DESC LIMIT 20""")
for r in cur.fetchall():
    print(f"  {r[0]:12s} {r[1]:6s} [{r[3]:15s}] {r[2][:60]}  ({r[4]})")

conn.close()
