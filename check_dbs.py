import sqlite3

dbs = ["data/sim.db", "data/sim_live_mirror.db"]
for db_path in dbs:
    print(f"\n=== {db_path} ===")
    try:
        db = sqlite3.connect(db_path)
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        print(f"Tables: {[t[0] for t in tables]}")
        for (name,) in tables:
            cnt = db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            print(f"  {name}: {cnt} rows")
        db.close()
    except Exception as e:
        print(f"  Error: {e}")
