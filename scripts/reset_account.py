#!/usr/bin/env python3
"""
清仓重置脚本：清空所有持仓，注入差额到10万初始资金
"""
import sqlite3
import os
from datetime import date

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'sim_live_mirror.db')

def reset_account():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 1. 获取当前账户
    cur.execute("SELECT * FROM sim_account WHERE id = 1")
    acct = dict(cur.fetchone())
    print(f'当前账户: cash={acct["cash"]:.2f}, total_value={acct["total_value"]:.2f}')
    
    # 2. 获取当前持仓
    cur.execute("SELECT stock_code, stock_name, quantity, current_price, market_value FROM sim_positions WHERE account_id = 1 AND quantity > 0")
    positions = cur.fetchall()
    
    total_sell = 0
    print(f'\n清仓 {len(positions)} 只持仓:')
    for p in positions:
        code, name, qty, price, mv = p
        print(f'  卖出 {code} {name} {qty}股 @ {price:.3f} = {mv:.2f}')
        total_sell += mv
    
    # 3. 清空持仓
    cur.execute("UPDATE sim_positions SET quantity = 0, market_value = 0, pnl = 0, pnl_pct = 0 WHERE account_id = 1")
    
    # 4. 计算清仓后现金
    cash_after_sell = float(acct['cash']) + total_sell
    print(f'\n清仓回收: {total_sell:.2f}')
    print(f'清仓后现金: {cash_after_sell:.2f}')
    
    # 5. 注入差额到10万
    target = 100000.0
    diff = target - cash_after_sell
    new_cash = cash_after_sell + diff
    new_total_value = new_cash  # 无持仓，总资产=现金
    
    print(f'\n注入差额: {diff:.2f}（目标 {target} - 当前 {cash_after_sell:.2f}）')
    print(f'重置后现金: {new_cash:.2f}')
    print(f'重置后总资产: {new_total_value:.2f}')
    
    cur.execute(
        "UPDATE sim_account SET cash = ?, total_value = ?, initial_cash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
        (round(new_cash, 2), round(new_total_value, 2), target)
    )
    
    # 6. 记录账户事件
    cur.execute(
        "INSERT INTO sim_account_events (account_id, event_type, event_date, old_initial_cash, new_initial_cash, old_total_value, new_total_value, reason, source, created_at) "
        "VALUES (?, 'reset', ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (1, str(date.today()), 100000.0, target, round(cash_after_sell, 2), round(new_total_value, 2),
         f'清仓重置：清仓回收{total_sell:.2f}，注入差额{diff:.2f}，重置到{target}初始资金', 'reset_script')
    )
    
    conn.commit()
    conn.close()
    
    print(f'\n✅ 重置完成！')
    print(f'   初始资金: {target:.2f}')
    print(f'   现金: {new_cash:.2f}')
    print(f'   总资产: {new_total_value:.2f}')

if __name__ == '__main__':
    reset_account()
