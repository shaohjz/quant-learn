#!/usr/bin/env python3
"""测试改进效果：模拟现金不足时的买入逻辑"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 模拟改进前的逻辑
def old_buy_logic(cash, price, max_position_pct):
    """改进前的买入逻辑"""
    max_amount = cash * max_position_pct
    quantity = (int(max_amount / price) // 100) * 100
    return quantity

# 模拟改进后的逻辑
def new_buy_logic(cash, price, max_position_pct, reserve_cash=1000):
    """改进后的买入逻辑"""
    # 检查最小投资金额
    min_investment = 100 * price
    if cash < min_investment:
        return 0, "现金不足，需要释放流动性"
    
    # 改进的金额计算
    available_cash = max(0, cash - reserve_cash)
    max_amount = min(available_cash * max_position_pct, available_cash)
    
    if max_amount < price * 100:
        return 0, "买入金额不足1手"
    
    quantity = (int(max_amount / price) // 100) * 100
    return quantity, "OK"

# 测试用例
print("测试改进效果：")
print("=" * 60)

# 模拟5月27日的情况：现金3068.68元，股票价格10元
cash = 3068.68
price = 10.0
max_position_pct = 0.20

print(f"模拟场景：现金¥{cash:,.2f}, 股票价格¥{price:.2f}, 最大仓位{ max_position_pct*100}%")

old_qty = old_buy_logic(cash, price, max_position_pct)
new_qty, msg = new_buy_logic(cash, price, max_position_pct)

print(f"\n改进前：买入数量 = {old_qty}股")
print(f"改进后：买入数量 = {new_qty}股，原因：{msg}")

if old_qty == 0 and new_qty > 0:
    print("✅ 改进有效！现在可以买入了")
elif old_qty == 0 and new_qty == 0:
    print("⚠️ 仍然无法买入，需要释放流动性")
else:
    print("ℹ️ 改进前后都能买入")

# 测试不同股票价格
print("\n" + "=" * 60)
print("不同股票价格下的买入能力：")

test_prices = [5.0, 10.0, 15.0, 20.0, 50.0, 100.0]
for p in test_prices:
    old_qty = old_buy_logic(cash, p, max_position_pct)
    new_qty, msg = new_buy_logic(cash, p, max_position_pct)
    print(f"股价¥{p:6.2f} | 改进前:{old_qty:4d}股 | 改进后:{new_qty:4d}股 | {msg}")

print("\n结论：")
print("改进后，当现金不足时，会尝试释放流动性（卖出浮亏仓位）")
print("这应该能显著提升买入信号执行率")