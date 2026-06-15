import sqlite3
from datetime import datetime, date

# ===== 连接PM库，添加需求单 =====
conn_pm = sqlite3.connect('data/pm.db')
cursor_pm = conn_pm.cursor()

# 获取下一个 task id
cursor_pm.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 1")
last_id = cursor_pm.fetchone()[0]
print(f"最后一个task id: {last_id}")

# 解析数字部分
import re
nums = re.findall(r'\d+', last_id)
if nums:
    next_num = int(nums[0]) + 1
    next_id = f"REQ-{next_num:03d}"
else:
    next_id = "REQ-089"

print(f"新task id: {next_id}")

conn_pm.close()
