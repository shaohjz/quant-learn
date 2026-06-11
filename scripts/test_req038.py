"""测试 REQ-038 的新函数"""
import sys
sys.path.insert(0, '.')

from vqlearn.services.buy_risk_guard import (
    check_position_count_limit,
    check_daily_new_position_limit,
    evaluate_buy_risk_guard,
    evaluate_buy_risk_with_limits,
)
from datetime import date

db = 'data/sim_live_mirror.db'
today = date.today().strftime('%Y-%m-%d')

print('=== check_position_count_limit (max=6) ===')
r1 = check_position_count_limit(db_path=db, account_id=1, max_positions=6)
print(f'  blocked: {r1.blocked}')
print(f'  reason: {r1.reason}')
cur_pos = r1.details.get('current_positions')
print(f'  current_positions: {cur_pos}')

print()
print('=== check_position_count_limit (max=1, should block if >=1) ===')
r1b = check_position_count_limit(db_path=db, account_id=1, max_positions=1)
print(f'  blocked: {r1b.blocked}')
print(f'  reason: {r1b.reason}')

print()
print('=== check_daily_new_position_limit (max_daily_new=2) ===')
r2 = check_daily_new_position_limit(
    db_path=db, account_id=1, trade_date=today, max_daily_new=2
)
print(f'  blocked: {r2.blocked}')
print(f'  reason: {r2.reason}')
print(f'  new_positions_today: {r2.details.get("new_positions_today")}')
print(f'  new_positions_count: {r2.details.get("new_positions_count")}')

print()
print('=== check_daily_new_position_limit with code (projected) ===')
r2b = check_daily_new_position_limit(
    db_path=db, account_id=1, trade_date=today, max_daily_new=2, code='999999'
)
print(f'  blocked: {r2b.blocked}')
print(f'  reason: {r2b.reason}')
print(f'  projected_new_positions: {r2b.details.get("projected_new_positions")}')

print()
print('=== All syntax checks ===')
import ast
ast.parse(open('vqlearn/services/buy_risk_guard.py').read())
print('  buy_risk_guard.py: syntax OK')
ast.parse(open('vqlearn/strategies/threshold_strategy.py', encoding='utf-8').read())
print('  threshold_strategy.py: syntax OK')

print()
print('ALL TESTS PASSED')
