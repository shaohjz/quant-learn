#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 process_armed_signals() 函数"""

import sys
sys.path.insert(0, '.')

from datetime import datetime
from scripts.portfolio_alert import process_armed_signals

now = datetime.now()
print(f"=== 测试 process_armed_signals @ {now.isoformat()} ===")
count, messages = process_armed_signals(now)
print(f"executed_count = {count}")
print(f"messages = {messages}")
print("=== 测试完成 ===")
