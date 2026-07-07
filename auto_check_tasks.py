import sqlite3
from datetime import datetime

# 自动检查并修复任务状态
conn = sqlite3.connect('data/pm.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# 查找所有open/pending/in_progress任务
c.execute("SELECT id, title, description, status, priority FROM tasks WHERE status IN ('open','pending','in_progress') ORDER BY priority")
tasks = c.fetchall()

print(f"需要检查的任务数: {len(tasks)}")
print("\n前10个任务:")
for i, t in enumerate(tasks[:10]):
    print(f"{i+1}. [{t['id']}] ({t['status']}) [{t['priority']}] {t['title']}")

conn.close()
