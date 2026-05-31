import sqlite3
import json
from datetime import datetime

conn = sqlite3.connect('data/pm.db')
c = conn.cursor()

print("=== PM 状态概览 ===\n")

# 1. 按状态统计
c.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")
print("状态分布:")
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]}")

# 2. testing/fixed 任务（容易阻塞）
print("\n=== Testing/Fixed 任务（可能阻塞）===")
c.execute("""
    SELECT id, title, status, priority, updated_at 
    FROM tasks 
    WHERE status IN ('testing', 'fixed') 
    ORDER BY updated_at DESC
""")
rows = c.fetchall()
if rows:
    for r in rows:
        print(f"  {r[0]}: {r[1]} [{r[2]}] pri={r[3]} updated={r[4]}")
else:
    print("  (无)")

# 3. in_progress 任务
print("\n=== In-Progress 任务 ===")
c.execute("""
    SELECT id, title, status, priority, created_at, updated_at
    FROM tasks 
    WHERE status = 'in_progress'
    ORDER BY updated_at DESC
""")
rows = c.fetchall()
for r in rows:
    print(f"  {r[0]}: {r[1]} [{r[2]}] pri={r[3]} created={r[4]} updated={r[5]}")

# 4. 最近的 pending 任务（新需求）
print("\n=== 最近 Pending 任务 (new) ===")
c.execute("""
    SELECT id, title, priority, created_at
    FROM tasks
    WHERE status = 'pending' AND type = 'story'
    ORDER BY created_at DESC
    LIMIT 10
""")
rows = c.fetchall()
for r in rows:
    print(f"  {r[0]}: {r[1]} pri={r[2]} created={r[3]}")

# 5. 检查是否有长时间未更新的 testing/fixed
print("\n=== 阻塞检查：长时间未更新的 testing/fixed ===")
c.execute("""
    SELECT id, title, status, priority, updated_at
    FROM tasks
    WHERE status IN ('testing', 'fixed')
    AND datetime(updated_at) < datetime('now', '-3 days')
""")
rows = c.fetchall()
if rows:
    print("  ⚠️ 以下任务长时间未更新，可能阻塞：")
    for r in rows:
        print(f"    {r[0]}: {r[1]} [{r[2]}] updated={r[4]}")
else:
    print("  ✅ 无长时间阻塞任务")

conn.close()
