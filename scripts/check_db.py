#!/usr/bin/env python3
"""检查数据库状态"""
import sqlite3
import os

db_path = "pm.db"
if not os.path.exists(db_path):
    print(f"数据库不存在: {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cur.fetchall()
print("数据库表:", [t[0] for t in tables])

for t in tables:
    tname = t[0]
    try:
        cur.execute(f'SELECT COUNT(*) FROM [{tname}]')
        cnt = cur.fetchone()[0]
        print(f"\n表 [{tname}]: {cnt} 行")
        if cnt > 0:
            cur.execute(f'SELECT * FROM [{tname}] ORDER BY rowid DESC LIMIT 3')
            rows = cur.fetchall()
            # 获取列名
            col_names = [desc[0] for desc in cur.description]
            print(f"  列: {col_names}")
            for row in rows:
                print(f"  最后行: {row}")
    except Exception as e:
        print(f"  错误: {e}")

conn.close()
