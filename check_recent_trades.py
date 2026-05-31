#!/usr/bin/env python3
"""检查最近的交易记录"""
import sqlite3

ROOT = "C:\\Users\\Administrator\\.openclaw\\workspace\\quant-learn"
DB = f"{ROOT}\\data\\sim_live_mirror.db"

def check_recent_trades():
    """检查最近的交易记录"""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 查看最近的交易记录
    cur.execute("""
        SELECT trade_date, stock_code, stock_name, direction, price, quantity, amount, signal_reason
        FROM sim_trades 
        WHERE trade_date >= '2026-05-20' 
        ORDER BY trade_date DESC, id DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    
    print('最近交易记录：')
    print('='*80)
    for r in rows:
        print(f'{r["trade_date"]} {r["direction"]} {r["stock_name"]}({r["stock_code"]}) {r["quantity"]}股 @ {r["price"]:.2f} 金额:{r["amount"]:.0f} 原因:{r["signal_reason"]}')
    
    # 统计买入信号执行情况
    cur.execute("""
        SELECT trade_date, COUNT(*) as buy_count
        FROM sim_trades 
        WHERE direction = 'BUY' AND trade_date >= '2026-05-20'
        GROUP BY trade_date
        ORDER BY trade_date DESC
    """)
    buy_stats = cur.fetchall()
    
    print('\n每日买入统计：')
    print('='*40)
    for r in buy_stats:
        print(f'{r["trade_date"]}: {r["buy_count"]}笔买入')
    
    conn.close()

if __name__ == "__main__":
    check_recent_trades()