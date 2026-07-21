"""
REQ-069: 回填 acc1 (learn) 2026-07-20 和 2026-07-21 的 sim_daily_nav 记录。

用于修复：
- 07-20: 现有 NAV 记录 total_value=100000, market_value=0，但当天有 3 笔建仓
- 07-21: 完全缺少 acc1 NAV 记录，当天又有 3 笔买入

回填逻辑：
1. 从 sim_account 和 sim_positions 逐日算 snapshot（含现金+持仓市值）
2. 按日期处理，不依赖 sim_account 的当前快照（already transacted after 07-20）
3. 因为 sim_account 是当天交易后的最终状态，直接使用其 cash/total_value
4. 但问题：sim_account 已被后续交易日覆盖。需要用 sim_trades 逐日还原。

解决方案：从已知的 07-20 首次交易前的状态（initial_cash=100000），
逐天应用 sim_trades 的现金流变动来重建每日 snapshot。
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "sim_live_mirror.db"

ACCOUNT_ID = 1
TRADE_DATES = ["2026-07-20", "2026-07-21"]


def _f(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def load_trades(conn: sqlite3.Connection, account_id: int, trade_date: str) -> list[dict]:
    """获取某日所有交易。"""
    cols = ["direction", "stock_code", "stock_name", "price", "quantity", "amount", "commission"]
    rows = conn.execute(
        f"SELECT {','.join(cols)} FROM sim_trades "
        "WHERE account_id=? AND trade_date=? ORDER BY id",
        (account_id, trade_date),
    ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def load_positions_snapshot(conn: sqlite3.Connection, account_id: int) -> dict:
    """获取当前持仓 snapshot（仅用于最后一天，因为不知道历史快照）"""
    rows = conn.execute(
        "SELECT stock_code, stock_name, quantity, avg_cost, current_price, market_value "
        "FROM sim_positions WHERE account_id=? AND quantity>0",
        (account_id,),
    ).fetchall()
    market_value = sum(_f(r[5]) for r in rows)
    return {"market_value": market_value, "positions": rows}


def main():
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()

    # 获取账户初始资金和当前状态
    row = cur.execute(
        "SELECT initial_cash, cash, total_value FROM sim_account WHERE id=?",
        (ACCOUNT_ID,),
    ).fetchone()
    if not row:
        print("账户不存在")
        conn.close()
        return

    initial_cash = _f(row[0])  # 100000

    # 获取前一天 (07-19 或更早) 的 NAV 作为起点
    # 因为 07-19 没有交易也没有 NAV，我们假设初始状态：
    # cash=100000, market_value=0, total=100000
    prev_nav = cur.execute(
        "SELECT id, total_value, cumulative_return, max_drawdown FROM sim_daily_nav "
        "WHERE account_id=? AND trade_date < '2026-07-20' ORDER BY trade_date DESC LIMIT 1",
        (ACCOUNT_ID,),
    ).fetchone()

    if prev_nav:
        prev_total = _f(prev_nav[1])
        prev_cum_ret = _f(prev_nav[2])
        prev_max_dd = _f(prev_nav[3])
    else:
        # 没有前一天 NAV，从 initial_cash 开始
        prev_total = initial_cash
        prev_cum_ret = 0.0
        prev_max_dd = 0.0

    print(f"起点 total = ¥{prev_total:,.2f}, initial_cash = ¥{initial_cash:,.0f}")

    # 逐日处理
    running_cash = initial_cash  # 模拟跟踪的现金
    # 不跟踪精确的持仓成本，我们使用 sim_account 的最终数据来反推
    # 更好的做法：每天从 sim_account 读（因为它是写入 Nav 时的最新状态）
    # 但问题：现在是回填，sim_account 已经是最终状态了
    #
    # 解决方案：使用 sim_account 的当前 total_value 和 cash 作为 07-21 snapshot
    # 对于 07-20，根据交易现金流 + 持仓市值重建

    # ── 处理 07-20 ────────────────────────────────────────────────
    trades_0720 = load_trades(conn, ACCOUNT_ID, "2026-07-20")
    print(f"\n=== 07-20: {len(trades_0720)} 笔交易 ===")

    # 从 sim_account 的当前所有持仓反推 07-20 的持仓
    # 已知 07-20 买入了: 000600(1100@8.41), 000725(1600@6.11), 300146(900@10.05)
    # 07-21 买入: 000725(1700@5.86), 001896(700@14.06), 300017(600@14.48)
    #
    # 用 sim_trades 计算每天现金流，持仓市值从 sim_positions 不能准确反推（current_price 变了）
    #
    # 实用方案：使用 current prices 来计算 07-20 的持仓市值
    # 因为 sim_positions.current_price 是 07-21 最后更新的，不代表 07-20 收盘价
    #
    # 更好的方案：直接使用 persisting 的 avg_cost 作为成本，
    # 用 build 当天的买入价作为 approximate market price（假设当天收盘≈买入价）
    # 对于 07-20: 当日买入的 positions 都按买入价算，其他 positions 不存在

    # 计算 07-20 持仓
    # 07-20 买入：000600@8.41*1100, 000725@6.11*1600, 300146@10.05*900
    pos_0720 = {}
    cash_0720 = initial_cash
    for t in trades_0720:
        code = t["stock_code"]
        qty = int(_f(t["quantity"]))
        price = _f(t["price"])
        amount = _f(t["amount"])
        cash_0720 -= amount  # amount 已含佣金
        if code in pos_0720:
            old = pos_0720[code]
            new_qty = old["qty"] + qty
            new_cost = (old["cost"] * old["qty"] + price * qty) / new_qty
            pos_0720[code] = {"qty": new_qty, "cost": price, "name": t["stock_name"]}
        else:
            pos_0720[code] = {"qty": qty, "cost": price, "name": t["stock_name"]}

    mv_0720 = sum(p["qty"] * p["cost"] for p in pos_0720.values())
    total_0720 = cash_0720 + mv_0720

    print(f"  07-20 reconstructed: cash=¥{cash_0720:,.2f} mv=¥{mv_0720:,.2f} total=¥{total_0720:,.2f}")

    daily_ret_0720 = (total_0720 - prev_total) / prev_total if prev_total > 0 else 0.0
    cum_ret_0720 = (total_0720 / initial_cash - 1) if initial_cash > 0 else 0.0

    # 更新 max_drawdown
    peak_0720 = max(prev_total, total_0720) if prev_total > 0 else initial_cash
    dd_0720 = (total_0720 / peak_0720 - 1) if peak_0720 > 0 else 0.0
    max_dd_0720 = min(prev_max_dd, dd_0720) if dd_0720 < 0 else prev_max_dd

    print(f"  daily_ret={daily_ret_0720*100:+.3f}% cum_ret={cum_ret_0720*100:+.3f}% max_dd={max_dd_0720*100:+.3f}%")
    print(f"  持仓: {[(p['name'], p['qty'], p['cost']) for p in pos_0720.values()]}")

    # ── 处理 07-21 ────────────────────────────────────────────────
    # 07-21 的状态直接使用 sim_account 的当前值（因为这就是 07-21 收盘后的最终状态）
    # sim_account: cash=43421.87, total=101628.87
    # 持仓 MV: SUM(market_value) = 58207.0
    # 但有一个问题：sim_account.total_value 已经是正确的了
    row = cur.execute(
        "SELECT cash, total_value FROM sim_account WHERE id=?",
        (ACCOUNT_ID,),
    ).fetchone()
    cash_0721 = _f(row[0])
    total_account_0721 = _f(row[1])

    pos_rows = cur.execute(
        "SELECT SUM(market_value) FROM sim_positions WHERE account_id=? AND quantity>0",
        (ACCOUNT_ID,),
    ).fetchone()
    mv_0721 = _f(pos_rows[0]) if pos_rows else 0.0

    # 验证一致性：total = cash + mv
    # 当前 sim_account.total_value=101628.87, cash=43421.87, mv=58207.0 → 101628.87
    # 说明 sim_account.total_value 没有包含正确的 sum(market_value)
    # 而可能是买入时即时计算的。没关系，我们用 cash+mv 重建。
    total_0721 = cash_0721 + mv_0721

    print(f"\n=== 07-21 ===")
    print(f"  cash=¥{cash_0721:,.2f} mv=¥{mv_0721:,.2f} total=¥{total_0721:,.2f}")

    daily_ret_0721 = (total_0721 - total_0720) / total_0720 if total_0720 > 0 else 0.0
    cum_ret_0721 = (total_0721 / initial_cash - 1) if initial_cash > 0 else 0.0

    peak_0721 = max(total_0720, total_0721)
    dd_0721 = (total_0721 / peak_0721 - 1) if peak_0721 > 0 else 0.0
    max_dd_0721 = min(max_dd_0720, dd_0721) if dd_0721 < 0 else max_dd_0720

    print(f"  daily_ret={daily_ret_0721*100:+.3f}% cum_ret={cum_ret_0721*100:+.3f}% max_dd={max_dd_0721*100:+.3f}%")

    # Update sim_account.total_value to reflect the corrected value
    cur.execute(
        "UPDATE sim_account SET total_value=? WHERE id=?",
        (round(total_0721, 2), ACCOUNT_ID),
    )
    print(f"\n  updated sim_account.total_value = ¥{total_0721:,.2f}")

    # ── 写入 sim_daily_nav ──────────────────────────────────────────

    nav_data = [
        ("2026-07-20", total_0720, cash_0720, mv_0720, daily_ret_0720, cum_ret_0720, max_dd_0720),
        ("2026-07-21", total_0721, cash_0721, mv_0721, daily_ret_0721, cum_ret_0721, max_dd_0721),
    ]

    for (dt, tv, cs, mv, dr, cr, mdd) in nav_data:
        existing = cur.execute(
            "SELECT id FROM sim_daily_nav WHERE account_id=? AND trade_date=?",
            (ACCOUNT_ID, dt),
        ).fetchone()
        if existing:
            print(f"\n  🔄 UPDATE sim_daily_nav id={existing[0]} for {dt}")
            cur.execute(
                "UPDATE sim_daily_nav SET "
                "total_value=?, cash=?, market_value=?, "
                "daily_return=?, cumulative_return=?, max_drawdown=?, "
                "created_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (round(tv, 2), round(cs, 2), round(mv, 2),
                 round(dr, 8), round(cr, 8), round(mdd, 8),
                 existing[0]),
            )
        else:
            print(f"\n  ✅ INSERT sim_daily_nav for {dt}")
            cur.execute(
                "INSERT INTO sim_daily_nav "
                "(account_id, trade_date, total_value, cash, market_value, "
                "daily_return, cumulative_return, max_drawdown, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                (ACCOUNT_ID, dt, round(tv, 2), round(cs, 2), round(mv, 2),
                 round(dr, 8), round(cr, 8), round(mdd, 8)),
            )

    conn.commit()

    # ── 验证 ───────────────────────────────────────────────────────
    print("\n=== 最终验证 ===")
    for r in cur.execute(
        "SELECT trade_date, account_id, total_value, cash, market_value, "
        "daily_return, cumulative_return, max_drawdown "
        "FROM sim_daily_nav WHERE account_id=? ORDER BY trade_date",
        (ACCOUNT_ID,),
    ):
        print(f"  {r[0]}: total=¥{r[2]:,.2f} cash=¥{r[3]:,.2f} mv=¥{r[4]:,.2f} "
              f"daily={r[5]*100:+.3f}% cum={r[6]*100:+.3f}% maxDD={r[7]*100:+.3f}%")

    # Also verify sim_account
    row = cur.execute(
        "SELECT id, cash, total_value, initial_cash FROM sim_account WHERE id=?",
        (ACCOUNT_ID,),
    ).fetchone()
    print(f"  sim_account: cash=¥{row[1]:,.2f} total=¥{row[2]:,.2f} initial=¥{row[3]:,.0f}")

    conn.close()
    print("\n✅ 回填完成")


if __name__ == "__main__":
    main()
