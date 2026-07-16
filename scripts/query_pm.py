import sqlite3, os, json

db_path = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db'
db = sqlite3.connect(db_path)

print("=== ACTIVE TASKS (status+priority) ===")
for t in db.execute("SELECT id, type, title, status, priority, assigned_to, created_at, updated_at, work_notes FROM tasks ORDER BY updated_at DESC").fetchall():
    print(f"\n[{t[3]}] [{t[4]}] {t[0]} - {t[2]} (type={t[1]}, assigned={t[5]})")
    print(f"  created={t[6]}, updated={t[7]}")
    if t[8]:
        print(f"  notes: {t[8][:300]}")

print("\n\n=== FRESHNESS ALERTS ===")
for a in db.execute("SELECT * FROM freshness_alerts ORDER BY check_time DESC").fetchall():
    print(a)

print("\n\n=== ARCHIVED TASKS (last 10) ===")
for t in db.execute("SELECT id, type, title, status, archived_at FROM tasks_archive ORDER BY archived_at DESC LIMIT 10").fetchall():
    print(f"[{t[3]}] {t[0]} - {t[2]} (archived={t[4]})")

db.close()
