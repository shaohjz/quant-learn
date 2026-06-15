import sqlite3
import re
from datetime import datetime, date

conn_pm = sqlite3.connect('data/pm.db')
cursor_pm = conn_pm.cursor()

# 检查现有task，找到最新id
cursor_pm.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 5")
rows = cursor_pm.fetchall()
print("最近task ids:", [r[0] for r in rows])

conn_pm.close()
