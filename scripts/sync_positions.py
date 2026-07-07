#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 sim_live_mirror.db 同步持仓数据到 broker.json
"""

import json
import sqlite3
from pathlib import Path

def sync_positions():
    """同步持仓数据"""
    
    # 读取 sim_live_mirror.db
    db_path = 'data/sim_live_mirror.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    positions_db = conn.execute(
        'SELECT * FROM sim_positions WHERE quantity > 0'
    ).fetchall()
    
    conn.close()
    
    print(f'从数据库读取 {len(positions_db)} 个持仓')
    
    # 转换为 broker.json 格式
    positions_broker = {}
    total_position_value = 0
    
    for pos in positions_db:
        code = pos['stock_code']
        positions_broker[code] = {
            'name': pos['stock_name'],
            'cost': pos['avg_cost'],
            'quantity': pos['quantity'],
            'buy_date': pos['buy_date'] if 'buy_date' in pos else '2026-06-28',
            'stop_loss': pos['avg_cost'] * 0.92,  # -8% 止损
            'take_profit': pos['avg_cost'] * 1.20,  # +20% 止盈
            'current_price': pos['current_price']
        }
        total_position_value += pos['current_price'] * pos['quantity']
    
    # 读取现有 broker.json
    broker_path = 'storage/broker.json'
    with open(broker_path, 'r', encoding='utf-8') as f:
        broker = json.load(f)
    
    # 更新持仓
    broker['positions'] = positions_broker
    
    # 更新账户信息
    initial_cash = 100000.0
    used_cash = sum(pos['avg_cost'] * pos['quantity'] for pos in positions_db)
    broker['account']['cash'] = initial_cash - used_cash
    broker['account']['total_assets'] = broker['account']['cash'] + total_position_value
    broker['account']['update_time'] = '2026-06-29 11:00:16'
    
    # 保存
    with open(broker_path, 'w', encoding='utf-8') as f:
        json.dump(broker, f, ensure_ascii=False, indent=2)
    
    print(f'✓ 同步完成')
    print(f'持仓数量: {len(positions_broker)}')
    print(f'现金: {broker["account"]["cash"]:.2f}')
    print(f'持仓总值: {total_position_value:.2f}')
    print(f'总资产: {broker["account"]["total_assets"]:.2f}')
    
    # 显示需要止损的股票
    print('\n⚠️ 需要止损的股票:')
    for code, pos in positions_broker.items():
        pnl_pct = (pos['current_price'] - pos['cost']) / pos['cost'] * 100
        if pnl_pct <= -8:
            print(f'{code} {pos["name"]}: 成本{pos["cost"]}, 现价{pos["current_price"]}, 浮盈亏{pnl_pct:.2f}%')

if __name__ == '__main__':
    sync_positions()
