import sqlite3
import os

# Connect to data/pm.db
db_path = 'data/pm.db'
if not os.path.exists(db_path):
    print(f"❌ {db_path} 不存在")
    exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Check current status of REQ-038
cursor.execute("SELECT * FROM tasks WHERE id='REQ-038'")
row = cursor.fetchone()

if row:
    print(f"REQ-038 当前状态:")
    print(f"  ID: {row['id']}")
    print(f"  标题: {row['title']}")
    print(f"  状态: {row['status']}")
    print(f"  优先级: {row['priority']}")
    print(f"  类型: {row['type']}")
    print(f"  创建时间: {row['created_at']}")
    print(f"  更新时间: {row['updated_at']}")
else:
    print("REQ-038 未找到")

conn.close()
