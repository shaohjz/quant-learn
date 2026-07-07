import sqlite3, os, json

base = r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data"

# PM DB
pm_db = os.path.join(base, "pm.db")
if os.path.exists(pm_db):
    conn = sqlite3.connect(pm_db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print("=== PM DB TABLES ===")
    print(tables)
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM [{t}]")
            print(f"  {t}: {cur.fetchone()[0]} rows")
            cur.execute(f"PRAGMA table_info([{t}])")
            cols = [c[1] for c in cur.fetchall()]
            print(f"    cols: {cols}")
            cur.execute(f"SELECT * FROM [{t}] LIMIT 50")
            rows = cur.fetchall()
            for r in rows:
                print(f"    {r}")
        except Exception as e:
            print(f"  {t}: ERROR - {e}")
    conn.close()
else:
    print("PM DB not found")

print("\n=== SIM LIVE MIRROR DB ===")
sim_db = os.path.join(base, "sim_live_mirror.db")
if os.path.exists(sim_db):
    conn = sqlite3.connect(sim_db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(tables)
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM [{t}]")
            print(f"  {t}: {cur.fetchone()[0]} rows")
            cur.execute(f"PRAGMA table_info([{t}])")
            cols = [c[1] for c in cur.fetchall()]
            print(f"    cols: {cols}")
            cur.execute(f"SELECT * FROM [{t}] LIMIT 20")
            rows = cur.fetchall()
            for r in rows:
                print(f"    {r}")
        except Exception as e:
            print(f"  {t}: ERROR - {e}")
    conn.close()
else:
    print("Sim DB not found")
