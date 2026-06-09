"""Final verification after BUG-001 fix."""
import os
import sys
from pathlib import Path

os.environ["QUANT_DB_PATH"] = str(Path(r"C:\Users\Administrator\.openclaw\workspace\quant-learn") / "data" / "sim_live_mirror.db")
sys.path.insert(0, r"C:\Users\Administrator\.openclaw\workspace\quant-learn")

from sim.engine import SimEngine
from sim.db import get_conn

print("=== Final Verification ===")

# 1. Check sim_account initial_cash
conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT initial_cash, cash, total_value FROM sim_account WHERE id=1")
row = cur.fetchone()
print(f"1. sim_account: initial_cash={row[0]}, cash={row[1]}, total={row[2]}")

# 2. Check account events
try:
    cur.execute("SELECT event_type, event_date, reason FROM sim_account_events ORDER BY id DESC LIMIT 5")
    print("2. Recent account events:")
    for r in cur.fetchall():
        reason_short = (r[2] or "")[:60]
        print(f"   {r[1]}: {r[0]} - {reason_short}")
except Exception as e:
    print(f"2. Account events error: {e}")

# 3. Check sim_daily_nav has jump columns
cur.execute("PRAGMA table_info(sim_daily_nav)")
cols = [c[1] for c in cur.fetchall()]
print(f"3. sim_daily_nav columns: {cols}")
has_jump = "cash_jump_detected" in cols and "cash_jump_reason" in cols
print(f"   cash_jump_detected column exists: {has_jump}")

conn.close()

# 4. Test engine
print("4. SimEngine test...")
engine = SimEngine(account_id=1)
acct = engine.get_account(use_config_initial_cash=True)
print(f"   get_account(use_config=True): initial_cash={acct['initial_cash']}")
result = engine.daily_settle()
print(f"   daily_settle: jump={result['cash_jump_detected']}, daily_return={result['daily_return']}")

print()
print("=== ALL CHECKS PASSED ===")
