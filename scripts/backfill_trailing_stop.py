"""
Backfill trailing_stop_price for existing positions.
Fixes TASK-20260716-2004-002: trailing stop not initialized for positions <5% profit.

For positions with NULL or cost-below trailing_stop_price,
set it to entry_price * 0.95 (5% stop loss).
"""
import sqlite3
import sys
sys.path.insert(0, r'C:\Users\Administrator\.openclaw\workspace\quant-learn')
from sim.db import get_default_trailing_stop

DB = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'

def main():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    
    positions = cur.execute(
        "SELECT id, stock_code, stock_name, avg_cost, trailing_stop_price, highest_price "
        "FROM sim_positions WHERE quantity > 0"
    ).fetchall()
    
    updated = 0
    for p in positions:
        cost = float(p['avg_cost'])
        current_ts = p['trailing_stop_price']
        
        if current_ts is None or float(current_ts) <= 0:
            new_ts = get_default_trailing_stop(cost)
            cur.execute(
                "UPDATE sim_positions SET trailing_stop_price = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_ts, p['id'])
            )
            print(f"  [FIXED] {p['stock_code']} {p['stock_name']}: trailing_stop {current_ts} -> {new_ts}")
            updated += 1
        elif float(current_ts) < cost:
            # Already has a stop but it's below cost (could be manual)
            new_ts = get_default_trailing_stop(cost)
            if new_ts > float(current_ts):
                cur.execute(
                    "UPDATE sim_positions SET trailing_stop_price = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_ts, p['id'])
                )
                print(f"  [RAISED] {p['stock_code']} {p['stock_name']}: trailing_stop {current_ts} -> {new_ts} (was below cost)")
                updated += 1
        else:
            print(f"  [OK] {p['stock_code']} {p['stock_name']}: trailing_stop={current_ts} (above cost={cost})")
    
    db.commit()
    db.close()
    print(f"\n✓ Updated {updated} positions.")

if __name__ == '__main__':
    main()
