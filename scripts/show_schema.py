"""Show table schemas for sim_live_mirror.db"""
import sqlite3
import os

BASE = r"C:\Users\Administrator\.openclaw\workspace\quant-learn"
mirror_db = os.path.join(BASE, "data", "sim_live_mirror.db")
c = sqlite3.connect(mirror_db)
c.row_factory = sqlite3.Row

for table in ["sim_positions", "sim_trades", "sim_account", "sim_daily_nav", "threshold_state"]:
    try:
        rows = c.execute(f"PRAGMA table_info({table})").fetchall()
        print(f"\n{table} columns:")
        for r in rows:
            print(f"  {r['name']} ({r['type']})")
    except Exception as e:
        print(f"\n{table}: ERROR - {e}")

c.close()
