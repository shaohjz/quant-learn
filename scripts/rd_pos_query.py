"""Quick query positions"""
import sqlite3
conn = sqlite3.connect("data/sim_live_mirror.db")
conn.row_factory = sqlite3.Row
pos = conn.execute("SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl, pnl_pct, trailing_stop_price, account_id FROM sim_positions WHERE quantity>0 ORDER BY account_id, pnl_pct").fetchall()
print("=== Active Positions ===")
for p in pos:
    ts = p["trailing_stop_price"]
    print("  acct={} {} {:8s} qty={} cost={} cur={} pnl={} pnl_pct={}% ts={}".format(
        p["account_id"], p["stock_code"], p["stock_name"] or "", p["quantity"],
        p["avg_cost"], p["current_price"], round(p["pnl"] or 0, 2),
        round(p["pnl_pct"] or 0, 2), ts))
conn.close()
