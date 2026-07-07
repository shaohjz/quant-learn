import sqlite3
from datetime import datetime

db = 'data/pm.db'
conn = sqlite3.connect(db)
cur = conn.cursor()

# 添加今日发现的新问题
new_tasks = [
    {
        'id': 'REQ-093',
        'type': 'bug',
        'title': '7/3 NAV异常跳变：total_value从169,031跳至228,917（+35.4%）',
        'description': '''2026-07-03 sim_daily_nav 记录显示 total_value 从 169,031.93 跳至 228,917.0（+35.4%），但当日交易仅买入龙旗科技(7,911元)和圆通速递(8,682元)，不可能产生约6万元收益。

根因怀疑：
1. sim_account 在 7/3 被某脚本错误更新（可能是 config_sync 将 initial_cash 改为 100,000 时误改了 total_value）
2. sim_daily_nav 写入逻辑用了错误的 cash 值（199,015 vs 真实 cash ~158,577）
3. NAV 计算脚本可能读取了错误数据源

影响：累计收益率计算错误（cumulative_return 被拉高至 14.46%，实际应为负值）

需排查：sim_account 在 7/3 12:19 前后的更新日志、daily_return 计算脚本''',
        'status': 'open',
        'priority': 'P0',
        'assigned_to': None,
    },
    {
        'id': 'REQ-094',
        'type': 'bug',
        'title': 'config_sync 误将 initial_cash 从 200,000 改为 100,000（方向错误）',
        'description': '''sim_account_events 显示 2026-07-03 12:16:35~12:19:32 期间连续触发 6 次 config_sync 事件，每次都将 initial_cash 从 200,000 改为 100,000，理由是"DB.initial_cash=200,000, config.initial_cash=100,000, 已自动同步 DB 至 config 值"。

问题：
1. 同步方向错误：应该是 config 跟随 DB，而不是 DB 跟随 config（DB 是真实资金来源）
2. 触发频率异常：6次重复 sync 说明去重逻辑失效
3. 已 fixed（REQ-071）但 7/3 仍在发生，说明修复未生效或回归

影响：initial_cash 被改为 100,000 后，所有基于 initial_cash 计算的收益率（cumulative_return）全部错误''',
        'status': 'open',
        'priority': 'P0',
        'assigned_to': None,
    },
    {
        'id': 'REQ-095',
        'type': 'data_error',
        'title': 'sim_daily_nav 在 7/3 后至今（7/6）未继续写入新记录',
        'description': '''sim_daily_nav 最新记录停留在 2026-07-03，距今已 3 天（7/4、7/5、7/6 均无记录）。
sim_account 的 updated_at 仍在更新（7/6 06:30:11），说明账户数据在更新，但 NAV 写入 cron 已失效。

需检查：
1. 每日收盘 NAV 写入 cron job 是否正常运行
2. db_stats.py 或类似脚本是否因异常而停止
3. 7/3 NAV 异常跳变后是否触发了某保护机制阻止后续写入''',
        'status': 'open',
        'priority': 'P1',
        'assigned_to': None,
    },
]

for task in new_tasks:
    # 检查是否已存在
    cur.execute("SELECT id FROM tasks WHERE id = ?", (task['id'],))
    if cur.fetchone():
        print(f"Task {task['id']} already exists, skipping...")
        continue
    
    cur.execute("""
        INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at, assigned_to)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'), ?)
    """, (task['id'], task['type'], task['title'], task['description'], task['status'], task['priority'], task['assigned_to']))
    print(f"Created task: {task['id']} - {task['title']}")

conn.commit()
conn.close()
print("\nDone!")
