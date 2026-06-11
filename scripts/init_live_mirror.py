#!/usr/bin/env python
"""
scripts/init_live_mirror.py - 初始化"实盘镜像"模拟账户

用户的真实持仓快照（5/19 11:30 截图）：
- 600330 天通股份  400 @32.818
- 002256 兆新股份  700 @5.246
- 002453 华软科技  300 @6.467
- 002342 巨力索具  100 @19.680
- 603601 再升科技  100 @17.830
- 现金: 2509.50

总本金: 25000

这个账户用来：
1. AI 自主决策：触发信号时虚拟买卖
2. 每日复盘对比：你的真实操作 vs AI 模拟
3. 跑一段时间后看哪个收益更好
"""
import sys, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 在 import db 前设置环境变量，强制把 DB 挪到 live_mirror 专属文件
os.environ['QUANT_DB_PATH'] = str(ROOT / 'data' / 'sim_live_mirror.db')
os.environ['QUANT_INITIAL_CASH'] = '25000'

from sim.db import get_conn, init_tables, DB_PATH
from sim.precision import fmt_cost, quantize_amount, quantize_cost, quantize_price

INITIAL_CASH = 25000.00

# 持仓快照（来自用户 5/19 11:30 截图 + 早上加买的再升科技）
POSITIONS = [
    # (code, name, qty, cost, current_price, market_value, pnl)
    ("600330", "天通股份", 400, 32.818, 29.020, 11608.00, -1519.13),
    ("002256", "兆新股份", 700, 5.246,  4.970,  3479.00,  -193.00),
    ("002453", "华软科技", 300, 6.467,  6.030,  1809.00,  -131.00),
    ("002342", "巨力索具", 100, 19.680, 15.740, 1574.00,  -394.00),
    ("603601", "再升科技", 100, 17.830, 17.780, 1778.00,  -5.02),
]


def main():
    print(f"📂 数据库路径: {DB_PATH}")
    print(f"💰 初始本金: {INITIAL_CASH:,.2f}")
    print(f"📊 初始持仓: {len(POSITIONS)} 只")
    
    # 1. 创建表
    init_tables()
    
    conn = get_conn()
    cur = conn.cursor()
    
    # 2. 重置账户
    normalized_positions = [
        (
            code,
            name,
            qty,
            quantize_cost(cost),
            quantize_price(cur_price),
            quantize_amount(mv),
            quantize_amount(pnl),
        )
        for code, name, qty, cost, cur_price, mv, pnl in POSITIONS
    ]
    market_value = quantize_amount(sum(p[5] for p in normalized_positions))
    cash = quantize_amount(INITIAL_CASH - sum(q * c for _, _, q, c, _, _, _ in normalized_positions))  # 现金 = 本金 - 已用成本
    total_value = quantize_amount(market_value + cash)
    
    print(f"\n💵 现金（本金-成本）: {cash:,.2f}")
    print(f"📦 当前市值: {market_value:,.2f}")
    print(f"📈 总市值: {total_value:,.2f}")
    print(f"📉 整体浮亏: {total_value - INITIAL_CASH:+.2f}")
    
    cur.execute("DELETE FROM sim_account")
    cur.execute(
        "INSERT INTO sim_account (id, account_name, initial_cash, cash, total_value) "
        "VALUES (1, 'live_mirror', ?, ?, ?)",
        (INITIAL_CASH, cash, total_value)
    )
    
    # 3. 清空旧持仓 + 插入新持仓
    cur.execute("DELETE FROM sim_positions")
    for code, name, qty, cost, cur_price, mv, pnl in normalized_positions:
        pnl_pct = (cur_price/cost - 1) * 100
        cur.execute(
            "INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
            (code, name, qty, cost, cur_price, mv, pnl, pnl_pct)
        )
    
    # 4. 写一条建仓"虚拟成交"作为基准（trade_date=今天）
    cur.execute("DELETE FROM sim_trades")
    from datetime import date
    today = date.today().isoformat()
    for code, name, qty, cost, _, _, _ in normalized_positions:
        cur.execute(
            "INSERT INTO sim_trades (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, tax, signal_reason, broker) "
            "VALUES (1, ?, ?, ?, 'BUY', ?, ?, ?, 0, 0, '初始化建仓快照（用户真实持仓）', 'live_mirror_init')",
            (today, code, name, cost, qty, quantize_amount(qty * cost))
        )
    
    conn.close()
    
    # 5. 验证
    print("\n✅ 持仓已写入：")
    print(f"{'代码':<10} {'名称':<10} {'数量':>5} {'成本':>8} {'现价':>8} {'市值':>10} {'盈亏':>10} {'%':>7}")
    print("-" * 75)
    for code, name, qty, cost, cur_p, mv, pnl in normalized_positions:
        pnl_pct = (cur_p/cost - 1) * 100
        print(f"{code:<10} {name:<10} {qty:>5} {fmt_cost(cost):>8} {cur_p:>8.3f} {mv:>10.2f} {pnl:>+10.2f} {pnl_pct:>+7.2f}%")
    print("-" * 75)
    print(f"{'TOTAL':<10} {'':<10} {sum(p[2] for p in normalized_positions):>5} {'':>8} {'':>8} {market_value:>10.2f} {sum(p[6] for p in normalized_positions):>+10.2f}")
    print(f"\n现金: {cash:,.2f}  总资产: {total_value:,.2f}  本金: {INITIAL_CASH:,.2f}  整体浮亏: {total_value - INITIAL_CASH:+.2f}")


if __name__ == "__main__":
    main()
