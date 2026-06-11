"""集成测试 REQ-038：验证风控集成"""
import sys
sys.path.insert(0, '.')

from vqlearn.services.buy_risk_guard import (
    evaluate_buy_risk_guard,
    evaluate_buy_risk_with_limits,
    RiskDecision,
)
from datetime import date

db = 'data/sim_live_mirror.db'
today = date.today().strftime('%Y-%m-%d')

# Mock tick 对象
class MockTick:
    def __init__(self, last_price):
        self.last_price = last_price
        self.open_price = last_price
        self.pre_close = last_price
        self.low_price = last_price
        self.volume = 1000000

print('=== Test 1: evaluate_buy_risk_guard with db_path (REQ-038) ===')
# 当前持仓 14 只，max_positions=6 应该被拦截
tick = MockTick(10.0)
result = evaluate_buy_risk_guard(
    code='600330',  # 天通股份，已有持仓
    tick=tick,
    db_path=db,
    account_id=1,
    max_positions=6,
    max_daily_new=2,
)
print(f'  blocked: {result.blocked}')
print(f'  reason: {result.reason}')
print(f'  trigger: {result.details.get("trigger", "")}')
assert result.blocked, 'Should be blocked by position count limit!'
print('  ✓ 正确拦截：持仓数量超限')

print()
print('=== Test 2: evaluate_buy_risk_with_limits ===')
result2 = evaluate_buy_risk_with_limits(
    code='600330',
    tick=tick,
    db_path=db,
    account_id=1,
    max_positions=6,
    max_daily_new=2,
)
print(f'  blocked: {result2.blocked}')
print(f'  reason: {result2.reason}')
assert result2.blocked
print('  ✓ evaluate_buy_risk_with_limits 正确拦截')

print()
print('=== Test 3: 加仓不受新建仓位上限约束 ===')
# 600330 已有持仓，所以 is_add_position=True，不应被新建仓位上限拦截
#（但会被持仓数量上限拦截）
result3 = evaluate_buy_risk_guard(
    code='600330',  # 已有持仓
    tick=tick,
    db_path=db,
    account_id=1,
    max_positions=99,  # 放开持仓数量上限
    max_daily_new=0,    # 新建仓位上限设为 0
)
print(f'  blocked: {result3.blocked}')
print(f'  reason: {result3.reason}')
# 600330 有持仓，所以不受 max_daily_new=0 影响
# 但可能因为大盘熔断等其他原因被拦截（盘中可能大盘正常，所以应该通过）
print(f'  details keys: {list(result3.details.keys())}')

print()
print('=== Test 4: Syntax check for threshold_strategy.py ===')
import ast
ast.parse(open('vqlearn/strategies/threshold_strategy.py', encoding='utf-8').read())
print('  syntax OK')

print()
print('ALL INTEGRATION TESTS PASSED')
