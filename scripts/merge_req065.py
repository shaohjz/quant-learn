import sqlite3
from datetime import datetime

db = sqlite3.connect('data/pm.db')
c = db.cursor()

# Merge REQ-066 into REQ-065: update REQ-065 description and work_notes, then delete REQ-066
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Get both
c.execute("SELECT * FROM tasks WHERE id IN ('REQ-065','REQ-066')")
for r in c.fetchall():
    print(f"{r[0]}: {r[1]} | {r[4]} | created={r[6]}")

# Update REQ-065 to note the merge and mark as in_progress since we're fixing it
c.execute("UPDATE tasks SET description=description || '\n\n[2026-06-13] REQ-066 与本需求完全相同，已合并。修复方案：web/app.py 的 DB_PATH 从 sim_live_mirror.db 改为 sim.db。', updated_at=?, status='fixed' WHERE id='REQ-065'", (now,))
print(f"REQ-065 updated: {c.rowcount} rows")

# Delete REQ-066
c.execute("DELETE FROM tasks WHERE id='REQ-066'")
print(f"REQ-066 deleted: {c.rowcount} rows")

db.commit()

# Also mark BUG-019 as fixed since we fixed the DB path
c.execute("UPDATE tasks SET status='fixed', updated_at=? WHERE id='BUG-019'", (now,))
print(f"BUG-019 updated: {c.rowcount} rows")

db.close()
print("Done.")
