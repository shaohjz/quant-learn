"""Quick test: can we connect to sim_live_mirror.db and query sim_account?"""
import os
import sys
sys.path.insert(0, ".")

os.environ["QUANT_DB_PATH"] = r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db"

from sim.db import get_conn

conn = get_conn()
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sim_account'")
r = cur.fetchone()
print("sim_account query result:", r)
if r:
    cur.execute("SELECT * FROM sim_account")
    row = cur.fetchone()
    print("sim_account row:", dict(row))
else:
    print("Tables in this DB:", [x[0] for x in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()])
conn.close()
print("OK")
