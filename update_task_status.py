import sqlite3
from datetime import datetime

# Connect to data/pm.db
db_path = 'data/pm.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Update REQ-038 status to in_progress
now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
cursor.execute(
    "UPDATE tasks SET status='in_progress', updated_at=? WHERE id='REQ-038'",
    (now,)
)
conn.commit()

print(f"✅ REQ-038 状态已更新为 in_progress")

# Verify the update
cursor.execute("SELECT id, title, status, updated_at FROM tasks WHERE id='REQ-038'")
row = cursor.fetchone()
print(f"验证: ID={row[0]}, 标题={row[1]}, 状态={row[2]}, 更新时间={row[3]}")

conn.close()
