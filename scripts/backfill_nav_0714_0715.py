"""补生成 learn 账户(acc1) 2026-07-14 和 2026-07-15 的 sim_daily_nav 记录"""
import sqlite3

DB = 'data/sim_live_mirror.db'
ACCOUNT_ID = 1
DATES = ['2026-07-14', '2026-07-15']

conn = sqlite3.connect(DB)
cur = conn.cursor()

for today in DATES:
    # 获取账户快照
    cur.execute("SELECT cash, total_value FROM sim_account WHERE id = ?", (ACCOUNT_ID,))
    acct = cur.fetchone()
    if not acct:
        print(f"[{today}] Account {ACCOUNT_ID} not found, skip")
        continue
    cash = float(acct[0])
    # 注意：sim_account.total_value 是快照值，可能包含持仓市值
    # 需要单独核算持仓
    cur.execute(
        "SELECT SUM(market_value) FROM sim_positions WHERE account_id = ? AND quantity > 0",
        (ACCOUNT_ID,)
    )
    mv_row = cur.fetchone()
    market_value = float(mv_row[0]) if mv_row and mv_row[0] else 0.0

    total_value = cash + market_value

    # 获取前一日NAV（找最近的）
    cur.execute(
        "SELECT total_value, cumulative_return, max_drawdown FROM sim_daily_nav "
        "WHERE account_id = ? AND trade_date < ? ORDER BY trade_date DESC LIMIT 1",
        (ACCOUNT_ID, today)
    )
    prev = cur.fetchone()
    if prev:
        prev_nav = float(prev[0])
        cumulative_return = float(prev[1]) if prev[1] is not None else 0
        prev_max_dd = float(prev[2]) if prev[2] is not None else 0
        daily_return = (total_value - prev_nav) / prev_nav if prev_nav > 0 else 0
        max_drawdown = min(prev_max_dd, daily_return) if daily_return < 0 else prev_max_dd
    else:
        daily_return = 0
        cumulative_return = 0
        max_drawdown = 0

    print(f"=== {today} ===")
    print(f"Cash: {cash:.2f}, Market Value: {market_value:.2f}, Total: {total_value:.2f}")
    print(f"Prev NAV: {prev_nav:.2f}" if prev else "No prev NAV")
    print(f"Daily Return: {daily_return:.6f}, Cumulative: {cumulative_return:.6f}, MaxDD: {max_drawdown:.6f}")

    # 幂等检查
    cur.execute(
        "SELECT id FROM sim_daily_nav WHERE account_id = ? AND trade_date = ?",
        (ACCOUNT_ID, today)
    )
    existing = cur.fetchone()
    if existing:
        print(f"  Updating existing row id={existing[0]}...")
        cur.execute(
            "UPDATE sim_daily_nav SET total_value=?, cash=?, market_value=?, "
            "daily_return=?, cumulative_return=?, max_drawdown=?, created_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (round(total_value, 2), round(cash, 2), round(market_value, 2),
             round(daily_return, 8), round(cumulative_return, 8), round(max_drawdown, 8),
             existing[0])
        )
    else:
        cur.execute(
            "INSERT INTO sim_daily_nav "
            "(account_id, trade_date, total_value, cash, market_value, "
            "daily_return, cumulative_return, max_drawdown, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (ACCOUNT_ID, today, round(total_value, 2), round(cash, 2), round(market_value, 2),
             round(daily_return, 8), round(cumulative_return, 8), round(max_drawdown, 8))
        )
        print(f"  Inserted NAV for {today}.")

conn.commit()

# Verify
print("\n=== Verification ===")
cur.execute(
    "SELECT trade_date, total_value, daily_return, cumulative_return FROM sim_daily_nav "
    "WHERE account_id = ? ORDER BY trade_date DESC LIMIT 5",
    (ACCOUNT_ID,)
)
for r in cur.fetchall():
    print(f"  {r[0]}: total={r[1]:.2f}, daily_ret={r[2]:.8f}, cum_ret={r[3]:.8f}")

conn.close()
print("\nDone.")
