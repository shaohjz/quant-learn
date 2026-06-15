import sqlite3, json, os
from datetime import datetime

pm_db = 'data/pm.db'

conn = sqlite3.connect(pm_db)
cursor = conn.cursor()

# 检查下一个 task id
cursor.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 1")
last_id = cursor.fetchone()[0]
print(f'最后一个 task id: {last_id}')

# 生成新 ID
prefix = ''.join([c for c in last_id if not c.isdigit()])
num = int(''.join([c for c in last_id if c.isdigit()]))
new_id = f"REQ-{num+1:03d}"
print(f'新 task id: {new_id}')

conn.close()
