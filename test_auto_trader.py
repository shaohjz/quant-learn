#!/usr/bin/env python3
"""测试自动交易执行器"""
import sys
from pathlib import Path

ROOT = Path("C:/Users/Administrator/.openclaw/workspace/quant-learn")
sys.path.insert(0, str(ROOT))

from scripts.auto_trader import AutoTrader

def test_auto_trader():
    """测试自动交易执行器"""
    print("=" * 60)
    print("测试自动交易执行器")
    print("=" * 60)
    
    # 创建自动交易执行器（干运行模式）
    trader = AutoTrader(account_id=1, dry_run=True)
    
    # 测试检查新信号
    print("\n1. 测试检查新信号...")
    signals = trader.check_new_signals()
    print(f"   发现 {len(signals)} 个新信号")
    
    # 测试计算买入数量
    print("\n2. 测试计算买入数量...")
    quantity = trader.calculate_buy_quantity("600519", 1800.0)
    print(f"   买入数量: {quantity} 股")
    
    # 测试计算卖出数量
    print("\n3. 测试计算卖出数量...")
    position = {
        "stock_code": "600519",
        "stock_name": "贵州茅台",
        "quantity": 100,
        "avg_cost": 1800.0,
        "current_price": 2000.0,
        "market_value": 200000.0,
    }
    signal = {
        "stock_code": "600519",
        "trigger_price": 2000.0,
    }
    sell_quantity = trader.calculate_sell_quantity(position, signal)
    print(f"   卖出数量: {sell_quantity} 股")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    test_auto_trader()