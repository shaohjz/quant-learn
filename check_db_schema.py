import sqlite3
import os

# 检查数据库文件
db_paths = [
    'data/sim.db',
    'data/sim_live_mirror.db',
    'data/pm.db'
]

for db_path in db_paths:
    if os.path.exists(db_path):
        print(f"\n=== {db_path} ===")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 获取所有表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        for table in tables:
            table_name = table[0]
            print(f"\n表: {table_name}")
            # 获取表结构
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            for col in columns:
                print(f"  - {col[1]} ({col[2]})")
        
        conn.close()
    else:
        print(f"\n{db_path} 不存在")
