#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试执行止损交易
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sim_executor import execute_trade

# 测试600330的止损
rule = {
    'code': '600330',
    'name': '天通股份',
    'level': 'stop_loss',
    'trigger': 30.19,
    'dir': 'below',
    'message': '自动止损 (-8%原始止损 ¥30.19, 浮盈亏 -9.65%)',
    'source': 'auto'
}

cur_price = 29.65

print('执行止损...')
result = execute_trade(rule, cur_price)
print(f'结果: {result}')
