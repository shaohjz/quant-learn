import sqlite3
conn = sqlite3.connect('data/sim_live_mirror.db')
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(f"Tables: {tables}")
if 'watchlist_history' in tables:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(watchlist_history)").fetchall()]
    print(f"watchlist_history cols: {cols}")
    cnt = conn.execute("SELECT COUNT(*) FROM watchlist_history").fetchone()[0]
    print(f"watchlist_history rows: {cnt}")
else:
    print("watchlist_history NOT FOUND - running migration...")
    sql = open('data/migrations/001_watchlist_history.sql', 'r').read()
    conn.executescript(sql)
    print("Migration done!")
    cols = [r[1] for r in conn.execute("PRAGMA table_info(watchlist_history)").fetchall()]
    print(f"watchlist_history cols: {cols}")
conn.close()
