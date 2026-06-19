#!/usr/bin/env python3
"""初始化 sim_live_mirror.db 的缺失表"""
import sys
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn')

import os
os.environ['QUANT_DB_PATH'] = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'

from sim.db import init_tables, get_conn

print('Running init_tables() on sim_live_mirror.db...')
init_tables()

# 验证 sim_account_events 表已创建
conn = get_conn()
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sim_account_events'")
r = c.fetchone()
print('sim_account_events table:', r)

# 查看 sim_account 当前内容
c.execute("SELECT id, account_name, initial_cash, cash, total_value FROM sim_account")
for row in c.fetchall():
    print('sim_account:', dict(row))

conn.close()
print('Done')
