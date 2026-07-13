import sqlite3
c = sqlite3.connect('data/pm.db')
c.row_factory = sqlite3.Row
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("TABLES:", tables)
for t in tables:
    cols = [d[1] for d in c.execute(f"PRAGMA table_info({t})")]
    print(f"\n== {t} cols: {cols}")
    for row in c.execute(f"SELECT * FROM {t}"):
        print(dict(row))
