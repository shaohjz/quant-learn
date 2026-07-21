import sqlite3, os
db = os.path.join('data','pm.db')
c = sqlite3.connect(db)
cur = c.cursor()
tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("TABLES:", tables)
for t in tables:
    print("\n=== SCHEMA", t, "===")
    for r in cur.execute(f"PRAGMA table_info({t})"):
        print(r)
    print("--- ROWS", t, "---")
    for r in cur.execute(f"SELECT * FROM {t}"):
        print(r)
