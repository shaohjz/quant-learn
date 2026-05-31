import sqlite3
import os

db_path = 'data/pm.db'
if not os.path.exists(db_path):
    print(f"DB not found: {db_path}")
else:
    conn = sqlite3.connect(db_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print("Tables:", tables)
    for t in tables:
        rows = conn.execute(f"SELECT * FROM {t} LIMIT 1").fetchall()
        print(f"  {t}: {len(rows)} row(s) sample")
        if rows:
            cols = [desc[0] for desc in conn.execute(f'PRAGMA table_info({t})').fetchall()]
            print(f"    columns: {cols}")
    conn.close()
