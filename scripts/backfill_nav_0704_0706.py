#!/usr/bin/env python3
"""
REQ-095: 补写 sim_daily_nav 2026-07-04 ~ 2026-07-06 缺失记录

问题：7/3 后没有新的 NAV 快照（7/4周六、7/5周日为非交易日，7/6周一交易日）
根因：daily_settle() 未被调用，cron 作业只做了价格更新但没有写入 NAV 快照。

策略：
- 7/4(周六): 继承 7/3 的 NAV（非交易日，保持前值）
- 7/5(周日): 继承 7/4 的 NAV（非交易日，保持前值）
- 7/6(周一): 使用账户当前 cash + 持仓 market_value 计算真实 NAV
"""

import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'sim_live_mirror.db')
ACCOUNT_ID = 1
INITIAL_CASH = 200000.0  # 从 config.yaml accounts.learn.initial_cash


def get_prev_nav(cur, account_id, before_date):
    """获取 before_date 之前最近的一条 NAV 记录"""
    cur.execute(
        "SELECT * FROM sim_daily_nav "
        "WHERE account_id = ? AND trade_date < ? "
        "ORDER BY trade_date DESC LIMIT 1",
        (account_id, before_date),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def insert_or_replace_nav(cur, account_id, trade_date, total_value, cash,
                          market_value, daily_return, cumulative_return,
                          max_drawdown, cash_jump_detected=0, cash_jump_reason=None):
    """INSERT OR REPLACE a NAV record"""
    cur.execute("""
        INSERT OR REPLACE INTO sim_daily_nav
        (account_id, trade_date, total_value, cash, market_value,
         daily_return, cumulative_return, max_drawdown,
         cash_jump_detected, cash_jump_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        account_id, trade_date, total_value, cash, market_value,
        daily_return, cumulative_return, max_drawdown,
        cash_jump_detected, cash_jump_reason,
    ))


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ========================================
    # 1. 获取 7/3 的 NAV（最后已知值）
    # ========================================
    prev = get_prev_nav(cur, ACCOUNT_ID, '2026-07-04')
    if not prev:
        print("❌ 没有找到 7/3 或更早的 NAV 记录，无法补写")
        conn.close()
        return

    print(f"📋 最后已知 NAV: {prev['trade_date']}")
    print(f"   总资产: ¥{prev['total_value']:,.2f}")
    print(f"   现金:   ¥{prev['cash']:,.2f}")
    print(f"   市值:   ¥{prev['market_value']:,.2f}")
    print(f"   日收益: {prev['daily_return']*100:+.2f}%" if prev['daily_return'] is not None else "   日收益: N/A")
    print()

    # 计算累计收益基础
    cumulative_base = (prev['total_value'] - INITIAL_CASH) / INITIAL_CASH if INITIAL_CASH else 0

    # ========================================
    # 2. 补写 7/4 (周六, 非交易日) — 继承 7/3 值
    # ========================================
    # 非交易日：daily_return = 0，其余保持不变
    insert_or_replace_nav(
        cur, ACCOUNT_ID, '2026-07-04',
        total_value=prev['total_value'],
        cash=prev['cash'],
        market_value=prev['market_value'],
        daily_return=0.0,  # 非交易日无收益
        cumulative_return=round(cumulative_base, 4),
        max_drawdown=prev['max_drawdown'],
        cash_jump_detected=0,
        cash_jump_reason='REQ-095 backfill: 非交易日(周六)继承前日NAV',
    )
    print("✅ 已补写 2026-07-04 (周六) NAV: 继承 7/3 值, daily_return=0")

    # ========================================
    # 3. 补写 7/5 (周日, 非交易日) — 继承 7/4 值
    # ========================================
    insert_or_replace_nav(
        cur, ACCOUNT_ID, '2026-07-05',
        total_value=prev['total_value'],
        cash=prev['cash'],
        market_value=prev['market_value'],
        daily_return=0.0,  # 非交易日无收益
        cumulative_return=round(cumulative_base, 4),
        max_drawdown=prev['max_drawdown'],
        cash_jump_detected=0,
        cash_jump_reason='REQ-095 backfill: 非交易日(周日)继承前日NAV',
    )
    print("✅ 已补写 2026-07-05 (周日) NAV: 继承 7/3 值, daily_return=0")

    # ========================================
    # 4. 补写 7/6 (周一, 交易日) — 使用真实账户数据
    # ========================================
    # 获取当前账户
    cur.execute("SELECT * FROM sim_account WHERE id = ?", (ACCOUNT_ID,))
    acct = dict(cur.fetchone())

    # 获取当前持仓市值
    cur.execute(
        "SELECT SUM(market_value) as mv FROM sim_positions "
        "WHERE account_id = ? AND quantity > 0",
        (ACCOUNT_ID,),
    )
    row = cur.fetchone()
    market_value = float(row['mv'] or 0)

    total_value = acct['cash'] + market_value
    daily_return_7_6 = (total_value - prev['total_value']) / prev['total_value'] if prev['total_value'] else 0
    cumulative_return_7_6 = (total_value - INITIAL_CASH) / INITIAL_CASH if INITIAL_CASH else 0

    # 计算 max_drawdown
    cur.execute(
        "SELECT MAX(total_value) as peak FROM sim_daily_nav WHERE account_id = ?",
        (ACCOUNT_ID,),
    )
    peak_row = cur.fetchone()
    peak = float(peak_row['peak'] or INITIAL_CASH)
    peak = max(peak, total_value)
    max_drawdown = (peak - total_value) / peak if peak > 0 else 0

    insert_or_replace_nav(
        cur, ACCOUNT_ID, '2026-07-06',
        total_value=round(total_value, 2),
        cash=round(acct['cash'], 2),
        market_value=round(market_value, 2),
        daily_return=round(daily_return_7_6, 6),
        cumulative_return=round(cumulative_return_7_6, 4),
        max_drawdown=round(max_drawdown, 4),
        cash_jump_detected=1,  # 7/3 → 7/6 跳变超过35%
        cash_jump_reason=(
            f"REQ-095 backfill: 7/3→7/6 间隔2个非交易日+1交易日, "
            f"总资产 ¥{prev['total_value']:,.2f}→¥{total_value:,.2f} "
            f"(跳变 {daily_return_7_6*100:+.2f}%)"
        ),
    )
    print(f"✅ 已补写 2026-07-06 (周一) NAV:")
    print(f"   总资产: ¥{total_value:,.2f}")
    print(f"   现金:   ¥{acct['cash']:,.2f}")
    print(f"   市值:   ¥{market_value:,.2f}")
    print(f"   日收益: {daily_return_7_6*100:+.2f}%")
    print(f"   累计:   {cumulative_return_7_6*100:+.2f}%")

    conn.commit()

    # ========================================
    # 5. 验证
    # ========================================
    print("\n" + "=" * 50)
    print("📊 验证: 最近 7 天 NAV")
    print("=" * 50)
    cur.execute(
        "SELECT trade_date, total_value, cash, market_value, daily_return, "
        "cumulative_return, max_drawdown, cash_jump_detected "
        "FROM sim_daily_nav "
        "WHERE account_id = ? AND trade_date >= '2026-06-30' "
        "ORDER BY trade_date ASC",
        (ACCOUNT_ID,),
    )
    for row in cur.fetchall():
        r = dict(row)
        dr = f"{r['daily_return']*100:+.2f}%" if r['daily_return'] is not None else "N/A"
        cr = f"{r['cumulative_return']*100:+.2f}%" if r['cumulative_return'] is not None else "N/A"
        jump = "⚠跳变" if r['cash_jump_detected'] else ""
        print(f"  {r['trade_date']} | 总资产 ¥{r['total_value']:,.2f} | "
              f"日{dr} | 累计{cr} {jump}")

    conn.close()
    print("\n✅ REQ-095 补写完成！")


if __name__ == '__main__':
    main()
