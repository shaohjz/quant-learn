import sqlite3, json

db_path = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'
db = sqlite3.connect(db_path)
db.row_factory = sqlite3.Row

# Check TASK-001: pnl_pct multiplied by 100
print("=== BUG CHECK: pnl_pct in sim_positions ===")
for p in db.execute("SELECT stock_code, stock_name, quantity, avg_cost, current_price, pnl, pnl_pct FROM sim_positions WHERE quantity > 0").fetchall():
    pnl_pct_computed = (p['current_price'] - p['avg_cost']) / p['avg_cost'] * 100 if p['avg_cost'] > 0 else 0
    print(f"{p['stock_code']} {p['stock_name']}: DB pnl_pct={p['pnl_pct']}, computed={pnl_pct_computed:.2f}%")

# Check TASK-002: trailing stop
print("\n=== BUG CHECK: trailing_stop_price in sim_positions ===")
for p in db.execute("SELECT stock_code, stock_name, avg_cost, trailing_stop_price, highest_price FROM sim_positions WHERE quantity > 0").fetchall():
    print(f"{p['stock_code']} {p['stock_name']}: avg_cost={p['avg_cost']}, trailing_stop={p['trailing_stop_price']}, highest={p['highest_price']}")

# Check TASK-003: TASK-20260709-2004-001 status
print("\n=== BUG CHECK: TASK-20260709-2004-001 (buy_zone串价) in pm.db ===")
pm_db = sqlite3.connect(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db')
pm_db.row_factory = sqlite3.Row
for t in pm_db.execute("SELECT * FROM tasks WHERE id='TASK-20260709-2004-001'").fetchall():
    print(f"Status: {t['status']}, Updated: {t['updated_at']}")
    print(f"Notes: {t['work_notes']}")

pm_db.close()
db.close()
