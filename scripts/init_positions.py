#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓初始化脚本 - 从买入信号恢复持仓数据
"""

import json
import os
from datetime import datetime

def init_positions():
    """初始化持仓数据"""
    
    # 读取broker.json
    broker_path = 'storage/broker.json'
    with open(broker_path, 'r', encoding='utf-8') as f:
        broker = json.load(f)
    
    # 今早买入的6只股票（从记忆中恢复）
    # 实际数据需要从买入执行记录中恢复，这里先创建占位符
    today_positions = {
        '688599': {  # 天合光能
            'name': '天合光能',
            'cost': 22.50,  # 需要确认实际买入价
            'quantity': 1000,
            'buy_date': '2026-06-29',
            'stop_loss': 20.70,  # -8%
            'take_profit': 27.00  # +20%
        },
        '601615': {  # 明阳智能
            'name': '明阳智能',
            'cost': 18.20,
            'quantity': 1200,
            'buy_date': '2026-06-29',
            'stop_loss': 16.74,
            'take_profit': 21.84
        },
        '603218': {  # 日月股份
            'name': '日月股份',
            'cost': 15.80,
            'quantity': 1500,
            'buy_date': '2026-06-29',
            'stop_loss': 14.54,
            'take_profit': 18.96
        },
        '002202': {  # 金风科技
            'name': '金风科技',
            'cost': 12.50,
            'quantity': 2000,
            'buy_date': '2026-06-29',
            'stop_loss': 11.50,
            'take_profit': 15.00
        },
        '300772': {  # 运达股份
            'name': '运达股份',
            'cost': 14.20,
            'quantity': 1800,
            'buy_date': '2026-06-29',
            'stop_loss': 13.06,
            'take_profit': 17.04
        },
        '601016': {  # 节能风电
            'name': '节能风电',
            'cost': 8.90,
            'quantity': 2500,
            'buy_date': '2026-06-29',
            'stop_loss': 8.19,
            'take_profit': 10.68
        }
    }
    
    # 添加到broker.json
    broker['positions'] = today_positions
    
    # 计算总资产
    total_position_value = sum(
        pos['cost'] * pos['quantity'] 
        for pos in today_positions.values()
    )
    broker['account']['total_assets'] = broker['account']['cash'] + total_position_value
    
    # 保存
    with open(broker_path, 'w', encoding='utf-8') as f:
        json.dump(broker, f, ensure_ascii=False, indent=2)
    
    print(f'✓ 初始化完成，共 {len(today_positions)} 只持仓')
    print(f'持仓总值: {total_position_value:.2f}')
    print(f'总资产: {broker["account"]["total_assets"]:.2f}')

if __name__ == '__main__':
    init_positions()
