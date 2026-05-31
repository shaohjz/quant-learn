"""测试脚本：检查数据库表并验证风控建议函数"""
import sqlite3
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
dbs = [
    (os.path.join(ROOT, "data", "sim.db"), "sim.db"),
    (os.path.join(ROOT, "data", "sim_live_mirror.db"), "sim_live_mirror.db"),
]

for db_path, db_name in dbs:
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        print(f"{db_name}: tables={tables}")
        if "sim_positions" in tables:
            cur.execute("SELECT COUNT(*) FROM sim_positions")
            cnt = cur.fetchone()[0]
            print(f"  sim_positions rows: {cnt}")
            if cnt > 0:
                cur.execute("SELECT stock_code, stock_name, pnl_pct FROM sim_positions LIMIT 5")
                for r in cur.fetchall():
                    print(f"    {r}")
        conn.close()
    else:
        print(f"{db_name}: NOT FOUND")

# Now test generate_risk_suggestions with sim_live_mirror.db
print("\n=== Testing generate_risk_suggestions with sim_live_mirror.db ===")
import tempfile

# Patch sim.db.get_conn to use sim_live_mirror.db
original_get_conn = None
try:
    sys.path.insert(0, ROOT)
    import sim.db as sim_db
    original_get_conn = sim_db.get_conn

    # Monkey-patch get_conn to use sim_live_mirror.db
    mirror_path = os.path.join(ROOT, "data", "sim_live_mirror.db")
    sim_db.DB_PATH = mirror_path  # This should redirect

    from sim.reporter import generate_risk_suggestions
    result = generate_risk_suggestions(account_id=1)
    print("Result:")
    print(result if result else "(无浮亏风险持仓)")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    if original_get_conn:
        sim_db.get_conn = original_get_conn
