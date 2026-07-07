#!/usr/bin/env python3
"""向 pm.db 添加今日复盘发现的新需求单"""
import sqlite3
import os
from datetime import datetime

PM_DB = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db'

conn = sqlite3.connect(PM_DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 获取下一个 REQ ID
cur.execute("SELECT id FROM tasks WHERE id LIKE 'REQ-%' ORDER BY id DESC LIMIT 1")
row = cur.fetchone()
if row:
    last_num = int(row['id'].split('-')[1])
else:
    last_num = 65
next_id = f"REQ-{last_num + 1:03d}"
print(f"Next ID: {next_id}")

tasks = [
    {
        'id': 'REQ-066',
        'type': 'bug',
        'title': 'REQ-066: sim_live_mirror 数据同步中断（数据过期24天）',
        'description': 'sim_live_mirror.db 数据最后更新于 2026-06-02 06:50:04，距今已 24 天（截至 2026-06-26）。\n'
                      'sim_account.updated_at、sim_positions.updated_at 均未更新，说明盘中写入链路完全中断。\n'
                      '同时 threshold_state 中有 6 条 armed 卖出信号自 6 月 2 日起积压未处理。\n'
                      '可能原因：1) vnpy OmsEngine 停止运行；2) sim_executor 写入失败；3) DB 连接异常。\n'
                      '需要检查 OmsEngine 状态、sim_executor 日志，并恢复数据写入。',
        'status': 'open',
        'priority': 'P0',
        'assigned_to': 'agent',
    },
    {
        'id': 'REQ-067',
        'type': 'story',
        'title': 'REQ-067: 数据新鲜度监控 — 超过1天未更新自动告警',
        'description': '当前无数据新鲜度监控，导致 sim_live_mirror 数据过期 24 天无人发现。\n'
                      '需求：1) 每日复盘时检查 sim_account.updated_at，若距今天数 >1 则告警；\n'
                      '2) 添加独立的数据健康检查 cron（每日 09:00 运行），检查各数据源可达性；\n'
                      '3) 告警推送到企微群。',
        'status': 'open',
        'priority': 'P1',
        'assigned_to': 'agent',
    },
    {
        'id': 'REQ-068',
        'type': 'bug',
        'title': 'REQ-068: threshold_state armed 信号积压无监控 — 6条信号积压24天',
        'description': 'threshold_state 中 6 条 armed/confirmed 卖出信号自 2026-06-02 起积压，至今未执行卖出。\n'
                      '积压信号列表：\n'
                      '1. 001896 豫能控股 take_profit armed (触发价17.2, 确认价18.33)\n'
                      '2. 002453 华软科技 trend_break armed (触发价5.66)\n'
                      '3. 301179 泽宇智能 trend_break armed (触发价22.43)\n'
                      '4. 600310 广西能源 take_profit armed (触发价5.76)\n'
                      '5. 600330 天通股份 trend_break armed (触发价28.05)\n'
                      '6. 603178 圣龙股份 trend_break armed (触发价17.16)\n'
                      '需求：1) 添加 armed 信号超时监控（armed 超过 1 天未处理则告警）；'
                      '2) 复盘脚本自动检查 threshold_state 中 status=armed 的记录，输出积压清单。',
        'status': 'open',
        'priority': 'P1',
        'assigned_to': 'agent',
    },
]

now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
for task in tasks:
    cur.execute(
        "INSERT INTO tasks (id, type, title, description, status, priority, created_at, updated_at, assigned_to) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task['id'],
            task['type'],
            task['title'],
            task['description'],
            task['status'],
            task['priority'],
            now,
            now,
            task['assigned_to'],
        )
    )
    print(f"✓ Added {task['id']}: {task['title']}")

conn.commit()
conn.close()
print(f"\nDone. {len(tasks)} tasks added.")
