import sqlite3

# Check recently closed bugs and open P0/P1 tasks
conn = sqlite3.connect(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db")
cur = conn.cursor()

# Detailed info on latest open/verified items
cur.execute("""
    SELECT id, type, title, status, priority, updated_at, 
           substr(result_notes,1,200) as notes_preview
    FROM tasks 
    WHERE status IN ('open','testing','in_progress','pending','fixed')
    ORDER BY 
        CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
        updated_at DESC
    LIMIT 20
""")
rows = cur.fetchall()
print("=== OPEN/ACTIVE TASKS (top 20 by priority) ===")
for r in rows:
    print(f"  [{r[3]}] {r[0]} ({r[1]}) {r[2]} | priority={r[4]} | updated={r[5]}")

# Check sim_live_mirror for recent activity
conn2 = sqlite3.connect(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db")
cur2 = conn2.cursor()

# Recent trades
cur2.execute("SELECT trade_date, stock_code, stock_name, direction, price, quantity, signal_reason FROM sim_trades ORDER BY id DESC LIMIT 10")
print("\n=== RECENT TRADES ===")
for r in cur2.fetchall():
    print(f"  {r[0]} {r[3]} {r[1]} {r[2]} @{r[4]}x{r[5]} | {r[6][:80] if r[6] else 'N/A'}")

# Recent NAV
cur2.execute("SELECT trade_date, total_value, cash, market_value, daily_return, max_drawdown FROM sim_daily_nav WHERE account_id=1 ORDER BY trade_date DESC LIMIT 5")
print("\n=== RECENT NAV (learn account) ===")
for r in cur2.fetchall():
    print(f"  {r[0]}: total={r[1]}, cash={r[2]}, mv={r[3]}, daily_ret={r[4]}, max_dd={r[5]}")

# Position summary
cur2.execute("SELECT account_id, COUNT(*) as cnt, SUM(market_value) as total_mv, SUM(pnl) as total_pnl FROM sim_positions GROUP BY account_id")
print("\n=== POSITION SUMMARY ===")
for r in cur2.fetchall():
    print(f"  account_id={r[0]}: {r[1]} positions, total_mv={r[2]}, total_pnl={r[3]}")

# Latest strategy shadow signals
cur2.execute("SELECT MAX(shadow_date) FROM strategy_shadow_signals")
print(f"\n=== LATEST SIGNAL DATE: {cur2.fetchone()[0]} ===")

# Latest review decisions (today)
cur2.execute("SELECT COUNT(*), MAX(trade_date) FROM review_decisions WHERE trade_date = '2026-07-06'")
r = cur2.fetchone()
print(f"=== TODAY REVIEW DECISIONS: count={r[0]}, date={r[1]} ===")

conn.close()
conn2.close()
