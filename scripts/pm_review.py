import sqlite3, json
from datetime import datetime

DB = "data/pm.db"
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("TABLES:", tables)

for t in tables:
    print("\n=== TABLE", t, "===")
    cur.execute(f"PRAGMA table_info({t})")
    cols = [c[1] for c in cur.fetchall()]
    print("COLS:", cols)
    cur.execute(f"SELECT * FROM {t}")
    rows = cur.fetchall()
    print("ROWS:", len(rows))
    for r in rows[:80]:
        print(dict(r))

con.close()
