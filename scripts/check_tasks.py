#!/usr/bin/env python3
"""检查 testing 和 fixed 状态的任务"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'pm.db')
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("=== 状态为 'testing' 的任务 ===")
cursor.execute("SELECT id, type, title, status FROM tasks WHERE status = 'testing' ORDER BY id")
testing_tasks = cursor.fetchall()
if testing_tasks:
    for row in testing_tasks:
        print(f"{row[0]} | {row[1]} | {row[2][:60]} | {row[3]}")
else:
    print("(无)")

print("\n=== 状态为 'fixed' 的任务 ===")
cursor.execute("SELECT id, type, title, status FROM tasks WHERE status = 'fixed' ORDER BY id")
fixed_tasks = cursor.fetchall()
if fixed_tasks:
    for row in fixed_tasks:
        print(f"{row[0]} | {row[1]} | {row[2][:60]} | {row[3]}")
else:
    print("(无)")

conn.close()
