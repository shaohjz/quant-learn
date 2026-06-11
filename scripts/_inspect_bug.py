import sqlite3, sys, json

c = sqlite3.connect('data/pm.db')
c.row_factory = sqlite3.Row
cur = c.cursor()
tid = sys.argv[1] if len(sys.argv) > 1 else 'BUG-013'

# list tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", [r[0] for r in cur.fetchall()])

# try common table names
for tbl in ('tasks', 'requirements', 'bugs', 'pm_tasks'):
    try:
        cur.execute(f"SELECT * FROM {tbl} WHERE id=?", (tid,))
        r = cur.fetchone()
        if r:
            print(f"\n--- From {tbl} ---")
            print(json.dumps(dict(r), ensure_ascii=False, indent=2))
    except Exception as e:
        pass
