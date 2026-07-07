#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手动执行真实账户的止损
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 设置真实账户
import os
os.environ['SIM_ACCOUNT_ID'] = '2'

from scripts.sim_executor import execute_trade, set_active_account

# 切换到真实账户
set_active_account(2)

# 执行600330的止损
print('执行 600330 天通股份 止损...')
rule1 = {
    'code': '600330',
    'name': '天通股份',
    'level': 'stop_loss',
    'trigger': 30.19,
    'dir': 'below',
    'message': '手动止损',
    'source': 'manual'
}
result1 = execute_trade(rule1, 29.57)
print(f'结果: {result1}')

print('\n执行 002453 华软科技 止损...')
rule2 = {
    'code': '002453',
    'name': '华软科技',
    'level': 'stop_loss',
    'trigger': 5.95,
    'dir': 'below',
    'message': '手动止损',
    'source': 'manual'
}
result2 = execute_trade(rule2, 4.40)
print(f'结果: {result2}')

print('\n执行 603601 再升科技 止损...')
rule3 = {
    'code': '603601',
    'name': '再升科技',
    'level': 'stop_loss',
    'trigger': 16.40,
    'dir': 'below',
    'message': '手动止损',
    'source': 'manual'
}
result3 = execute_trade(rule3, 11.91)
print(f'结果: {result3}')

# 切回学习账户
set_active_account(1)
print('\n✓ 已切换回学习账户')
