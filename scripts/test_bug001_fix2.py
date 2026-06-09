"""Test engine.py after REQ-001 fix - with detailed debug."""
import os
import sys
from pathlib import Path

# Project root is the workspace directory (where config.yaml lives)
PROJECT_ROOT = Path(r"C:\Users\Administrator\.openclaw\workspace\quant-learn")
os.environ["QUANT_DB_PATH"] = str(PROJECT_ROOT / "data" / "sim_live_mirror.db")
print("QUANT_DB_PATH:", os.environ["QUANT_DB_PATH"])

sys.path.insert(0, str(PROJECT_ROOT))

# Verify sim/db.py get_conn connects to the right DB
from sim.db import get_conn

conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sim_account'")
r = cur.fetchone()
print("sim_account exists in connected DB:", r)
if not r:
    print("ERROR: sim_account table not found!")
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    print("Tables in this DB:", [x[0] for x in cur.fetchall()])
    conn.close()
    sys.exit(1)
conn.close()

print("\nImporting SimEngine...")
from sim.engine import SimEngine
print("SimEngine imported OK")

print("Creating SimEngine(account_id=1)...")
engine = SimEngine(account_id=1)
print("SimEngine created OK")

acct = engine.get_account()
print(f"get_account(): initial_cash={acct['initial_cash']}, cash={acct['cash']}, total={acct['total_value']}")

acct2 = engine.get_account(use_config_initial_cash=True)
print(f"get_account(use_config=True): initial_cash={acct2['initial_cash']}")

print("\nAll tests passed!")
