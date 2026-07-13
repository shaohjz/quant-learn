import sys, os
sys.path.insert(0, '.')
os.chdir(r'C:\Users\Administrator\.openclaw\workspace\quant-learn')

import sim.db as db
conn = db.get_conn()
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("Tables:", tables)

# Count rows
for t in ['sim_account', 'sim_positions', 'sim_trades', 'sim_daily_nav', 'threshold_state', 'strategy_shadow_signals']:
    if t in tables:
        r = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()
        print(f"  {t}: {r[0]} rows")

conn.close()

# Check web app for syntax issues
try:
    import py_compile
    py_compile.compile(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\web\app.py', doraise=True)
    print("\nweb/app.py: syntax OK")
except py_compile.PyCompileError as e:
    print(f"\nweb/app.py: SYNTAX ERROR - {e}")

# Check sim engine 
try:
    py_compile.compile(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\sim\engine.py', doraise=True)
    print("sim/engine.py: syntax OK")
except py_compile.PyCompileError as e:
    print(f"sim/engine.py: SYNTAX ERROR - {e}")
