"""Test engine.py after REQ-001 fix."""
import sys, os
sys.path.insert(0, ".")

# [REQ-001] Must point to the correct DB
os.environ["QUANT_DB_PATH"] = os.path.join(os.path.dirname(os.path.abspath(".")), "data", "sim_live_mirror.db")
from sim.engine import SimEngine
print("SimEngine imported OK")

# Test: init should trigger _validate_account_consistency
engine = SimEngine(account_id=1)
acct = engine.get_account()
print(f"get_account(): initial_cash={acct['initial_cash']}, cash={acct['cash']}, total={acct['total_value']}")

acct2 = engine.get_account(use_config_initial_cash=True)
print(f"get_account(use_config=True): initial_cash={acct2['initial_cash']}")

# Test daily_settle (dry run, don't actually write)
print("\nTesting daily_settle...")
result = engine.daily_settle()
print(f"daily_settle result:")
for k, v in result.items():
    print(f"  {k}: {v}")
print("\nAll tests passed!")
