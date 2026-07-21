import sqlite3, os

for db_name in ['data/pm.db', 'data/sim_live_mirror.db']:
    db_path = os.path.join(r'C:\Users\Administrator\.openclaw\workspace\quant-learn', db_name)
    print(f"\n=== {db_name} ===")
    if not os.path.exists(db_path):
        print("  NOT FOUND")
        continue
    db = sqlite3.connect(db_path)
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print(f"  Tables: {tables}")
    for t in tables:
        count = db.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
        print(f"    {t}: {count} rows")
        # show schema
        cols = db.execute(f"PRAGMA table_info([{t}])").fetchall()
        print(f"      Columns: {[(c[1],c[2]) for c in cols]}")
    db.close()
