#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sqlite3, os
from datetime import datetime

pm_db = os.path.join(os.path.expanduser('~'), '.openclaw', 'workspace', 'quant-learn', 'data', 'pm.db')
conn = sqlite3.connect(pm_db)
cur = conn.cursor()

now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# 检查最新 REQ 编号
cur.execute("SELECT id FROM tasks WHERE id LIKE 'REQ-%%' AND id GLOB 'REQ-[0-9][0-9][0-9]' ORDER BY id DESC LIMIT 1")
last = cur.fetchone()
print('Latest numeric REQ:', last)

# 添加新任务
new_tasks = [
    ('REQ-070', 'bug', 'sim_positions 中存在测试脏数据（Test0/Test1/Test2）',
     'sim_positions 表中有 3 条测试仓位记录（stock_code=000000/000001/000002，stock_name=Test0/Test1/Test2），会影响每日复盘和 NAV 计算准确性。需要清理这些脏数据。',
     'open', 'P2'),
    ('REQ-071', 'bug', 'config_sync 事件频繁触发：initial_cash 配置不一致',
     '检测到 6 次 config_sync 事件。config 中 initial_cash=100,000，但 DB 中 initial_cash=200,000，每次 engine.init 都触发自动同步。建议统一配置来源（config vs DB），避免反复 sync。',
     'open', 'P1'),
    ('REQ-072', 'bug', 'real_portfolio(account_id=2) 在 sim_daily_nav 中无任何 NAV 记录',
     'account_id=2（real_portfolio）在 sim_daily_nav 表中完全没有记录，无法计算该账户的收益率和回撤。需要确认数据写入逻辑是否覆盖 account_id=2。',
     'open', 'P1'),
]

for tid, ttype, title, desc, status, pri in new_tasks:
    cur.execute('SELECT id FROM tasks WHERE id=?', (tid,))
    if cur.fetchone():
        print('已存在:', tid)
    else:
        sql = """INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
        cur.execute(sql, (tid, ttype, title, desc, status, pri, now, now))
        print('已添加:', tid, title)

conn.commit()
conn.close()
print('Done')
