#!/usr/bin/env python3
"""检查账户状态和现金情况"""
import sqlite3
from datetime import datetime, timedelta

ROOT = "C:\\Users\\Administrator\\.openclaw\\workspace\\quant-learn"
DB = f"{ROOT}\\data\\sim_live_mirror.db"

def check_account_status():
    """检查账户状态"""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 查看账户表
    cur.execute("SELECT * FROM sim_account WHERE id = 1")
    account = cur.fetchone()
    
    if account:
        print("账户状态：")
        print("=" * 50)
        print(f"账户ID: {account['id']}")
        print(f"账户名称: {account['account_name']}")
        print(f"初始资金: {account['initial_cash']:,.2f}")
        print(f"可用现金: {account['cash']:,.2f}")
        print(f"总资产: {account['total_value']:,.2f}")
        print(f"更新时间: {account['updated_at']}")
        
        # 计算资金使用率
        if account['initial_cash'] > 0:
            usage_pct = (account['initial_cash'] - account['cash']) / account['initial_cash'] * 100
            print(f"资金使用率: {usage_pct:.1f}%")
        
        # 检查5月27日的账户快照（如果有daily_settle表）
        try:
            cur.execute("""
                SELECT * FROM sim_daily_settle 
                WHERE account_id = 1 AND trade_date = '2026-05-27'
            """)
            settle = cur.fetchone()
            if settle:
                print("\n5月27日结算快照：")
                print(f"现金: {settle['cash']:,.2f}")
                print(f"总资产: {settle['total_value']:,.2f}")
        except:
            pass
    
    # 查看5月27日的持仓
    cur.execute("""
        SELECT stock_code, stock_name, quantity, avg_cost, current_price, market_value
        FROM sim_positions 
        WHERE account_id = 1 AND quantity > 0
        ORDER BY market_value DESC
    """)
    positions = cur.fetchall()
    
    if positions:
        print("\n5月27日持仓（如果从快照恢复）：")
        print("=" * 80)
        total_market_value = 0
        for p in positions:
            print(f"{p['stock_name']}({p['stock_code']}) {p['quantity']}股 @成本{p['avg_cost']:.2f} 现值{p['current_price']:.2f} 市值{p['market_value']:,.2f}")
            total_market_value += p['market_value']
        
        if account:
            available_cash = account['cash']
            total_assets = available_cash + total_market_value
            print(f"\n估算总资产: {total_assets:,.2f} (现金{available_cash:,.2f} + 市值{total_market_value:,.2f})")
    else:
        print("\n5月27日无持仓")
    
    conn.close()

if __name__ == "__main__":
    check_account_status()