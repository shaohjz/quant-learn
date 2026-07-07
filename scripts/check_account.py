#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查持仓的 account_id
"""

import sqlite3
from pathlib import Path

db_path = 'data/sim_live_mirror.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# 查询所有持仓及其account_id
positions = conn.execute('SELECT * FROM sim_positions WHERE quantity > 0').fetchall()

print('持仓及account_id:')
for pos in positions:
    account_id = pos['account_id']
    code = pos['stock_code']
    name = pos['stock_name']
    print(f'account_id={account_id}, {code} {name}')

# 也检查 sim_account 表
print('\n账户列表:')
accounts = conn.execute('SELECT * FROM sim_account').fetchall()
for acct in accounts:
    print(f'id={acct["id"]}, name={acct["account_name"]}, cash={acct["cash"]}, total_value={acct["total_value"]}')

conn.close()
