import sqlite3
import json
from datetime import datetime

DB = "data/pm.db"

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
cur = c.cursor()

# list tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("TABLES:", tables)

for t in tables:
    print("\n=== TABLE:", t, "===")
    cur.execute(f"PRAGMA table_info({t})")
    cols = [r[1] for r in cur.fetchall()]
    print("COLS:", cols)
    cur.execute(f"SELECT * FROM {t} LIMIT 50")
    rows = cur.fetchall()
    for r in rows:
        print(dict(r))

c.close()
