import sqlite3
import os
from datetime import datetime, date

workspace = "C:/Users/Administrator/.openclaw/workspace/quant-learn"
pm_db = f"{workspace}/data/pm.db"

conn = sqlite3.connect(pm_db)
cur = conn.cursor()

# 获取下一个 REQ ID
cur.execute("SELECT id FROM tasks WHERE id LIKE 'REQ-%' ORDER BY id DESC LIMIT 1")
last_id = cur.fetchone()[0]  # e.g. REQ-068
last_num = int(last_id.split('-')[1])
new_id = f"REQ-{last_num+1:03d}"

print(f"新任务 ID: {new_id}")

# 今日发现的新问题，提需求单
new_tasks = [
    {
        "id": new_id,
        "type": "bug",
        "title": f"{new_id}: sim_live_mirror.db 镜像功能未生效 — 仅含 review_reflections 表",
        "description": """sim_live_mirror.db 设计目的为 sim.db 的镜像/同步数据库，用于双账户复盘对比。

当前实际状态（2026-06-14 检查）：
- sim_live_mirror.db 仅包含 2 张表：review_reflections、sqlite_sequence
- 缺少 sim_account / sim_positions / sim_trades / sim_daily_nav 等核心表
- REQ-065 已标记 fixed，但实际数据库文件未更新（需要执行 init_tables 或数据迁移）

影响：
- 双账户复盘报告中 live_mirror 部分始终为空或过期
- 无法进行有效的模拟盘 vs 实盘对比分析

修复建议：
1. 检查 sim_live_mirror init 脚本是否正确创建了所有表
2. 若表结构正确，需增加 sim.db → sim_live_mirror.db 的定时同步任务
3. 在双账户复盘脚本中增加镜像库可用性检测""",
        "status": "open",
        "priority": "P1",
        "created_at": "2026-06-14 20:07:00",
        "updated_at": "2026-06-14 20:07:00",
        "assigned_to": None,
        "result_notes": None,
        "root_cause": None,
        "fix_commit": None,
        "work_notes": "由 quant-finance-manager 周日复盘自动发现并提单"
    }
]

# 插入新任务
for task in new_tasks:
    cur.execute("""
        INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at, assigned_to, result_notes, root_cause, fix_commit, work_notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task["id"], task["type"], task["title"], task["description"],
        task["status"], task["priority"], task["created_at"], task["updated_at"],
        task["assigned_to"], task["result_notes"], task["root_cause"], task["fix_commit"], task["work_notes"]
    ))
    print(f"已插入: {task['id']} - {task['title']}")

conn.commit()
conn.close()
print("\n完成！")
