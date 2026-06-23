#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试多策略简报生成（带超时和调试）"""

import sys
import signal
from pathlib import Path
from datetime import datetime
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def timeout_handler(signum, frame):
    print("\n⏱️ 执行超时（60秒）")
    sys.exit(1)

# 设置超时
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(60)

try:
    print("开始导入模块...")
    from sim.signal_generator import generate_signals
    from sim.notifier import send_markdown
    from sim.stock_pool import StockPool
    from sim.realtime_price import get_latest_prices
    print("✅ 模块导入成功\n")

    print("获取股票池...")
    pool = StockPool()
    all_stocks = pool.get_all()
    print(f"✅ 股票池获取成功，共 {len(all_stocks)} 只\n")

    print("开始生成信号（可能较慢）...")
    signals = []
    count = 0
    for stock_code, stock_name in all_stocks.items():
        count += 1
        print(f"[{count}/{len(all_stocks)}] 处理 {stock_code}({stock_name})...", end=" ")
        try:
            signal.alarm(10)  # 每只股票最多10秒
            signal_obj = generate_signals(stock_code, stock_name)
            signals.append(signal_obj)
            print(f"✅ 信号: {signal_obj.get('signal', 'UNKNOWN')}")
        except Exception as e:
            print(f"❌ 错误: {e}")
            traceback.print_exc()
        finally:
            signal.alarm(60)  # 恢复总体超时
    
    print(f"\n✅ 信号生成完成，共 {len(signals)} 个")
    
    # 统计
    buy_signals = [s for s in signals if s.get("signal") == "BUY"]
    sell_signals = [s for s in signals if s.get("signal") == "SELL"]
    hold_signals = [s for s in signals if s.get("signal") == "HOLD"]
    
    print(f"买入信号: {len(buy_signals)}")
    print(f"卖出信号: {len(sell_signals)}")
    print(f"持有信号: {len(hold_signals)}")
    
except Exception as e:
    print(f"\n❌ 发生错误: {e}")
    traceback.print_exc()
finally:
    signal.alarm(0)  # 取消超时
