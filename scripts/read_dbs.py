import sqlite3
import os
import json
from datetime import datetime

workspace = "C:/Users/Administrator/.openclaw/workspace/quant-learn"
sim_db = f"{workspace}/data/sim_live_mirror.db"
pm_db = f"{workspace}/data/pm.db"

print("=" * 60)
print("=== sim_live_mirror.db ===")
print("=" * 60)
conn = sqlite3.connect(sim_db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 获取所有表
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("表列表:", tables)

for t in tables:
    print(f"\n--- 表: {t} ---")
    try:
        cur.execute(f'SELECT * FROM [{t}]')
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        print(f"列: {cols}")
        print(f"行数: {len(rows)}")
        for r in rows[:10]:  # 最多显示10行
            row_dict = dict(r)
            # 截断过长字段
            for k, v in row_dict.items():
                if isinstance(v, str) and len(v) > 200:
                    row_dict[k] = v[:200] + "..."
            print(row_dict)
        if len(rows) > 10:
            print(f"... 还有 {len(rows)-10} 行")
    except Exception as e:
        print('Error:', e)

conn.close()

print("\n" + "=" * 60)
print("=== pm.db ===")
print("=" * 60)
conn = sqlite3.connect(pm_db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("表列表:", tables)

for t in tables:
    print(f"\n--- 表: {t} ---")
    try:
        cur.execute(f'SELECT * FROM [{t}]')
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]
        print(f"列: {cols}")
        print(f"行数: {len(rows)}")
        for r in rows[:10]:
            row_dict = dict(r)
            for k, v in row_dict.items():
                if isinstance(v, str) and len(v) > 200:
                    row_dict[k] = v[:200] + "..."
            print(row_dict)
        if len(rows) > 10:
            print(f"... 还有 {len(rows)-10} 行")
    except Exception as e:
        print('Error:', e)

conn.close()
