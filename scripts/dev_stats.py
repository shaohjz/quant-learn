import sqlite3
db = sqlite3.connect(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db')
db.row_factory = sqlite3.Row
cur = db.cursor()

# 按状态统计
cur.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status ORDER BY cnt DESC")
print("=== Task Status Summary ===")
for r in cur.fetchall():
    print(f"  {r['status']:15s} {r['cnt']:3d}")

# 按类型和优先级统计open/in_progress/testing
for s in ['open','in_progress','testing']:
    cur.execute("SELECT type, priority, COUNT(*) as cnt FROM tasks WHERE status=? GROUP BY type, priority ORDER BY priority", (s,))
    rows = cur.fetchall()
    if rows:
        print(f"\n  -- {s} breakdown --")
        for r in rows:
            print(f"    {r['type']:6s} {r['priority']:4s} x{r['cnt']}")

# 本周更新的任务
print("\n=== 本周(6/23-6/27)有更新的任务 ===")
cur.execute("SELECT id, title, status, priority, updated_at FROM tasks WHERE updated_at >= '2026-06-23' ORDER BY updated_at DESC")
for r in cur.fetchall():
    print(f"  [{r['priority']}] {r['id']:12s} {r['status']:12s} {r['title'][:70]}")

# 未关闭的bug
print("\n=== 未关闭的Bug ===")
cur.execute("SELECT id, title, status, priority FROM tasks WHERE type='bug' AND status NOT IN ('verified','fixed','done','deployed')")
for r in cur.fetchall():
    print(f"  [{r['priority']}] {r['id']:12s} {r['status']:12s} {r['title'][:60]}")

db.close()
