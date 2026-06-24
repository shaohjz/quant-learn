#!/usr/bin/env python3
"""Backfill trailing_stop_price for positions where it is NULL."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

if not DB_PATH.exists():
    DB_PATH = ROOT / "data" / "sim.db"
    if not DB_PATH.exists():
        print("No DB found!")
        exit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

positions = conn.execute(
    "SELECT id, account_id, stock_code, avg_cost, current_price, trailing_stop_price "
    "FROM sim_positions WHERE quantity > 0"
).fetchall()

print(f"Total positions: {len(positions)}")
null_count = 0
updated = 0

for pos in positions:
    tsp = pos['trailing_stop_price']
    if tsp is None or tsp == 0:
        null_count += 1
        avg_cost = float(pos['avg_cost'] or pos['current_price'] or 0)
        if avg_cost <= 0:
            print(f"  SKIP {pos['stock_code']}: avg_cost={avg_cost}")
            continue
        init_stop = round(avg_cost * 0.92, 2)
        conn.execute(
            "UPDATE sim_positions SET trailing_stop_price=? WHERE id=?",
            (init_stop, pos['id'])
        )
        updated += 1
        print(f"  UPDATE {pos['stock_code']}: trailing_stop_price = ¥{init_stop:.2f} (avg_cost ¥{avg_cost:.2f} × 0.92)")
    else:
        print(f"  OK   {pos['stock_code']}: trailing_stop_price = ¥{tsp:.2f}")

conn.commit()
conn.close()

print()
print(f"Summary: {null_count} positions had NULL trailing_stop_price, {updated} updated.")
