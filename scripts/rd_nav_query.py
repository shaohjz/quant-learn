"""Check NAV data"""
import sqlite3
conn = sqlite3.connect("data/sim_live_mirror.db")
conn.row_factory = sqlite3.Row
nav = conn.execute("SELECT trade_date, account_id, total_value, cash, market_value, daily_return, cumulative_return FROM sim_daily_nav WHERE account_id IN (1,3) ORDER BY trade_date DESC LIMIT 10").fetchall()
for n in nav:
    print(dict(n))
conn.close()
