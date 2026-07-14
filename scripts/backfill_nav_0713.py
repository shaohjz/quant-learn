"""补生成 2026-07-13 的 sim_daily_nav 记录"""
import sqlite3
from datetime import date

conn = sqlite3.connect('data/sim_live_mirror.db')
cur = conn.cursor()

account_id = 1
today = '2026-07-13'

# 获取账户
cur.execute("SELECT cash FROM sim_account WHERE id = ?", (account_id,))
acct = cur.fetchone()
cash = float(acct[0]) if acct else 0.0

# 获取持仓市值
cur.execute(
    "SELECT SUM(market_value) FROM sim_positions WHERE account_id = ? AND quantity > 0",
    (account_id,)
)
mv_row = cur.fetchone()
market_value = float(mv_row[0]) if mv_row and mv_row[0] else 0.0

total_value = cash + market_value

# 获取上个交易日NAV(07-10)
cur.execute(
    "SELECT total_value, cumulative_return, max_drawdown FROM sim_daily_nav "
    "WHERE account_id = ? AND trade_date = '2026-07-10' ORDER BY id DESC LIMIT 1",
    (account_id,)
)
prev = cur.fetchone()
if prev:
    prev_nav = float(prev[0])
    cumulative_return = float(prev[1])
    prev_max_dd = float(prev[2])
    daily_return = (total_value - prev_nav) / prev_nav if prev_nav > 0 else 0
    max_drawdown = max(prev_max_dd, -daily_return if daily_return < 0 else 0)
else:
    daily_return = 0
    cumulative_return = 0
    max_drawdown = 0

print(f"Cash: {cash:.2f}")
print(f"Market Value: {market_value:.2f}")
print(f"Total Value: {total_value:.2f}")
print(f"Daily Return: {daily_return:.6f}")
print(f"Cumulative Return: {cumulative_return:.6f}")
print(f"Max Drawdown: {max_drawdown:.6f}")

# 检查幂等
cur.execute(
    "SELECT id FROM sim_daily_nav WHERE account_id = ? AND trade_date = ?",
    (account_id, today)
)
existing = cur.fetchone()
if existing:
    print(f"NAV for {today} already exists (id={existing[0]}), updating...")
    cur.execute(
        "UPDATE sim_daily_nav SET total_value=?, cash=?, market_value=?, "
        "daily_return=?, cumulative_return=?, max_drawdown=?, created_at=CURRENT_TIMESTAMP "
        "WHERE id=?",
        (round(total_value, 2), round(cash, 2), round(market_value, 2),
         round(daily_return, 8), round(cumulative_return, 8), round(max_drawdown, 8),
         existing[0])
    )
    print("Updated.")
else:
    cur.execute(
        "INSERT INTO sim_daily_nav "
        "(account_id, trade_date, total_value, cash, market_value, "
        "daily_return, cumulative_return, max_drawdown, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (account_id, today, round(total_value, 2), round(cash, 2), round(market_value, 2),
         round(daily_return, 8), round(cumulative_return, 8), round(max_drawdown, 8))
    )
    print(f"Inserted NAV for {today}.")

conn.commit()
conn.close()
print("Done.")
