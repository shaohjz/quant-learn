#!/usr/bin/env python3
"""检查 fixed 和 testing 状态的任务"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pm.db"

def check_tasks():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 检查 fixed 状态的任务
        cursor.execute(
            "SELECT id, title, status FROM tasks WHERE status='fixed'"
        )
        fixed_tasks = cursor.fetchall()
        
        print(f"Fixed 状态的任务 ({len(fixed_tasks)} 个):")
        for task in fixed_tasks:
            print(f"  {task['id']}: {task['title']}")
        
        print()
        
        # 检查 testing 状态的任务
        cursor.execute(
            "SELECT id, title, status FROM tasks WHERE status='testing'"
        )
        testing_tasks = cursor.fetchall()
        
        print(f"Testing 状态的任务 ({len(testing_tasks)} 个):")
        for task in testing_tasks:
            print(f"  {task['id']}: {task['title']}")

if __name__ == "__main__":
    check_tasks()
