"""检查 learn 账户状态"""
import sys
sys.path.insert(0, '.')
from sim.portfolio import fetch_account, fetch_positions, learn_account_id, learn_max_total_value

acc_id = learn_account_id()
acc = fetch_account(acc_id)
positions = fetch_positions(acc_id)
max_tv = learn_max_total_value()

print(f"=== learn 账户 (id={acc_id}) ===")
print(f"  现金: {acc['cash']:,.2f}")
print(f"  total_value(db): {acc['total_value']:,.2f}")
print(f"  max_total_value 上限: {max_tv:,.2f}")
print()
print(f"=== 持仓 ({len(positions)} 只) ===")
total_mv = 0
for p in positions:
    mv = p['market_value'] or 0
    total_mv += mv
    print(f"  {p['stock_code']} {p['stock_name']:8s} qty={p['quantity']:>5} "
          f"cost={p['avg_cost']:>8.3f} cur={p['current_price']:>8.3f} mv={mv:>10,.2f}")
print(f"  持仓市值合计: {total_mv:,.2f}")
print(f"  现金+持仓: {acc['cash'] + total_mv:,.2f}")
print(f"  距上限差额: {max_tv - (acc['cash'] + total_mv):,.2f}")
