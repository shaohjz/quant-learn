import sqlite3
import os
from datetime import datetime

workspace = "C:/Users/Administrator/.openclaw/workspace/quant-learn"
sim_db = f"{workspace}/data/sim.db"

print("=" * 60)
print("=== sim.db (模拟盘数据库) ===")
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
        for r in rows[:20]:  # 最多显示20行
            row_dict = dict(r)
            # 截断过长字段
            for k, v in row_dict.items():
                if isinstance(v, str) and len(v) > 200:
                    row_dict[k] = v[:200] + "..."
            print(row_dict)
        if len(rows) > 20:
            print(f"... 还有 {len(rows)-20} 行")
    except Exception as e:
        print('Error:', e)

conn.close()

# 也读取 sim_live_mirror.db 真实内容
print("\n" + "=" * 60)
print("=== sim_live_mirror.db (镜像数据库) ===")
print("=" * 60)
mirror_db = f"{workspace}/data/sim_live_mirror.db"
conn = sqlite3.connect(mirror_db)
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
        for r in rows[:20]:
            row_dict = dict(r)
            for k, v in row_dict.items():
                if isinstance(v, str) and len(v) > 200:
                    row_dict[k] = v[:200] + "..."
            print(row_dict)
        if len(rows) > 20:
            print(f"... 还有 {len(rows)-20} 行")
    except Exception as e:
        print('Error:', e)

conn.close()
