import sqlite3

db = sqlite3.connect("data/sim_live_mirror.db")
db.row_factory = sqlite3.Row

# Check strategy_shadow_signals schema
print("=== strategy_shadow_signals ===")
cols = db.execute("PRAGMA table_info(strategy_shadow_signals)").fetchall()
for c in cols:
    print(f"  {c[1]} ({c[2]})")

# Check a sample row
row = db.execute("SELECT * FROM strategy_shadow_signals LIMIT 1").fetchone()
if row:
    print("Sample row:")
    for k in row.keys():
        print(f"  {k} = {row[k]}")

db.close()
