#!/usr/bin/env python3
"""检查 testing 和 fixed 状态的任务"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "pm.db"

with sqlite3.connect(DB_PATH) as conn:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, type, title, status, priority FROM tasks WHERE status IN ('testing', 'fixed') ORDER BY id"
    )
    rows = cursor.fetchall()
    
    if not rows:
        print("✅ 当前没有需要测试的任务")
        print("   - testing 状态：0 个")
        print("   - fixed 状态：0 个")
    else:
        print(f"📋 找到 {len(rows)} 个待测试任务：\n")
        for row in rows:
            task_id, task_type, title, status, priority = row
            icon = "🧪" if status == "testing" else "🔧"
            print(f"{icon} [{task_id}] ({status}) [{priority}] {title}")
