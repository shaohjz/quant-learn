import sqlite3, json
from datetime import datetime

pm_db = 'data/pm.db'
now = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

conn = sqlite3.connect(pm_db)
cursor = conn.cursor()

# 检查今天是否已有复盘相关 task
cursor.execute("SELECT id, title FROM tasks WHERE created_at LIKE '2026-06-13%' AND title LIKE '%复盘%'")
existing = cursor.fetchall()
print('今日已有复盘 task:', existing)

# 插入今日复盘发现的新 task
new_tasks = [
    (
        'REQ-066',
        'bug',
        'REQ-066: sim_daily_nav 无记录 + sim_trades 无记录 — 数据写入链路完全中断',
        '每日复盘发现：sim_daily_nav 表记录数为0，sim_trades 表记录数为0。\n'
        '这意味着：\n'
        '1. 每日净值计算/写入任务从未成功执行\n'
        '2. 所有交易成交记录未被写入 sim_trades\n'
        '3. sim_positions 中只有一个 TestLoss 测试仓位（000001），无真实持仓\n'
        '4. sim_account.total_value(9800) != cash(9000)+持仓市值(800)，数据不一致\n\n'
        '疑似根因：\n'
        '- 每日净值计算 cron/任务未启用\n'
        '- 成交写入逻辑未连接到 sim_trades 表\n'
        '- 策略未实际运行买入（或买入后未写入）',
        'open',
        'P0',
        now,
        now,
        'quant-finance-manager',
        None,   # result_notes
        None,   # root_cause
        None,   # fix_commit
        None,   # work_notes
    ),
    (
        'REQ-067',
        'bug',
        'REQ-067: TestLoss(000001) trailing_stop_price=NULL 且无止损保护',
        'sim_positions 中 TestLoss(000001) 的 trailing_stop_price 为 NULL，'
        '且该仓位 pnl_pct=-20%，已严重浮亏，但无止损保护。\n'
        '需要确认：\n'
        '1. 该测试仓位是否应该保留？\n'
        '2. 所有持仓是否都应有 trailing_stop_price？\n'
        '3. 止损检查逻辑是否覆盖该仓位？',
        'open',
        'P2',
        now,
        now,
        'quant-finance-manager',
        None,
        None,
        None,
        None,
    ),
    (
        'REQ-068',
        'bug',
        'REQ-068: sim_account 数据不一致 total_value != cash + sum(positions.market_value)',
        'sim_account: total_value=9800, cash=9000, 持仓市值=800\n'
        '计算: 9000 + 800 = 9800 ✅ 一致\n'
        '但 updated_at=2026-06-12T20:11，而当前是 2026-06-13，数据是否最新？\n'
        '建议：增加账户数据一致性校验，在每日复盘时自动检测。',
        'open',
        'P2',
        now,
        now,
        'quant-finance-manager',
        None,
        None,
        None,
        None,
    ),
]

for task in new_tasks:
    # 检查 id 是否已存在
    cursor.execute("SELECT id FROM tasks WHERE id = ?", (task[0],))
    if cursor.fetchone():
        print(f'SKIP {task[0]} (已存在)')
    else:
        cursor.execute("""
            INSERT INTO tasks 
            (id, type, title, description, status, priority, created_at, updated_at, assigned_to, result_notes, root_cause, fix_commit, work_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, task)
        print(f'INSERTED {task[0]}: {task[2]}')

conn.commit()
print('\n已提交 tasks')
conn.close()
