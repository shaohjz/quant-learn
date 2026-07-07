#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
强制清仓600330
"""

import os
import sqlite3
from pathlib import Path

# 直接操作数据库，强制删除持仓
db_path = 'data/sim_live_mirror.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# 查询600330的剩余持仓
pos = conn.execute('SELECT * FROM sim_positions WHERE account_id=2 AND stock_code="600330"').fetchone()

if pos:
    quantity = pos['quantity']
    avg_cost = pos['avg_cost']
    current_price = pos['current_price']
    
    print(f'600330 剩余持仓: {quantity}股')
    print(f'成本: {avg_cost}, 现价: {current_price}')
    
    # 计算卖出所得
    sell_amount = current_price * quantity
    commission = sell_amount * 0.00025  # 万2.5
    stamp_tax = sell_amount * 0.0005  # 万5
    net_amount = sell_amount - commission - stamp_tax
    
    print(f'卖出所得: ¥{net_amount:.2f}')
    
    # 更新账户现金
    conn.execute(
        'UPDATE sim_account SET cash=cash+?, total_value=total_value+? WHERE id=2',
        (net_amount, net_amount)
    )
    
    # 删除持仓
    conn.execute(
        'DELETE FROM sim_positions WHERE account_id=2 AND stock_code="600330"'
    )
    
    # 写入交易记录
    from datetime import datetime
    trade_date = datetime.now().strftime('%Y-%m-%d')
    trade_time = datetime.now().strftime('%H:%M:%S')
    
    conn.execute(
        'INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, stock_name, direction, price, quantity, amount, commission, signal_reason) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        (2, trade_date, trade_time, '600330', '天通股份', 'SELL', current_price, quantity, net_amount, commission, '强制清仓')
    )
    
    conn.commit()
    print(f'✓ 已强制清仓600330')
    
    # 检查账户状态
    acct = conn.execute('SELECT * FROM sim_account WHERE id=2').fetchone()
    print(f'\n真实账户状态:')
    print(f'  cash: {acct["cash"]}')
    print(f'  total_value: {acct["total_value"]}')
    
else:
    print('600330 已清仓，无需操作')

conn.close()
