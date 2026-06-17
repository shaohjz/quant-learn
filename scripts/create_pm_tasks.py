import sqlite3, os, json
from datetime import datetime

pm_db = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db'

conn = sqlite3.connect(pm_db)
cursor = conn.cursor()

# Check current max id
cursor.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 1")
row = cursor.fetchone()
max_id = row[0] if row else ''
print(f'Last task id: {max_id}')

# Parse last task number
import re
if max_id and max_id.startswith('REQ-'):
    last_num = int(max_id.split('-')[1])
else:
    last_num = 73

new_id = f'REQ-{last_num+1:03d}'
print(f'New task id: {new_id}')

# Insert new tasks based on today's findings

tasks = []

# Task 1: sim_trades 依然为空
tasks.append({
    'id': new_id,
    'type': 'bug',
    'title': 'sim_trades 表持续为空，交易溯源完全断裂（2026-06-16复盘）',
    'description': '2026-06-16 复盘发现 sim.db 的 sim_trades 表仍然为空（0条记录），但 sim_positions 中存在 000001 平安银行 100股的持仓记录。\n\n这意味着：\n1. 该持仓来源不明，无开仓交易记录\n2. 所有盈亏计算无法追溯\n3. 策略回测和实盘对比无法进行\n4. 资金去向不明（初始10万，现总资产约1万）\n\n建议：\n1. 彻底清理 sim.db 中的测试数据，重新初始化\n2. 确保后续所有交易（含手动）必须写入 sim_trades\n3. 增加数据完整性约束：持仓必须有对应 sim_trades 记录',
    'status': 'open',
    'priority': 'P0',
    'assigned_to': 'quant-agent',
    'result_notes': '数据质量P0问题，阻塞实盘对接',
    'root_cause': '测试数据管理混乱，交易写入链路未打通',
    'work_notes': '2026-06-16 复盘中再次确认'
})

new_id2 = f'REQ-{last_num+2:03d}'
tasks[-1]['id'] = new_id

# Task 2: total_value 未更新（2026-06-15的total_value，今天是16日）
tasks.append({
    'id': new_id2,
    'type': 'bug',
    'title': 'sim_account.total_value 未每日更新，数据延迟（2026-06-16复盘）',
    'description': 'sim_account.updated_at = 2026-06-15 10:36:22，今天是 2026-06-16，但账户数据未更新。\n\nsim_daily_nav 最新记录也是 2026-06-15，缺少 2026-06-16 的 NAV 记录。\n\n这意味着每日净值计算任务（daily_settle）未正常运行。\n\n影响：\n- 策略基于过期账户数据做决策\n- 日报数据不准确\n- 止损/止盈检查基于旧价格',
    'status': 'open',
    'priority': 'P1',
    'assigned_to': 'quant-agent',
    'result_notes': '需要检查 daily_settle cron 任务是否启用',
    'root_cause': '每日结算任务未运行',
    'work_notes': '2026-06-16 复盘发现'
})

# Insert tasks
for t in tasks:
    cursor.execute("""
        INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at, assigned_to, result_notes, root_cause, work_notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        t['id'],
        t['type'],
        t['title'],
        t['description'],
        t['status'],
        t['priority'],
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        t['assigned_to'],
        t['result_notes'],
        t['root_cause'],
        t['work_notes']
    ))
    print(f'Created: {t["id"]} - {t["title"]}')

conn.commit()
conn.close()
print('\nDone!')
