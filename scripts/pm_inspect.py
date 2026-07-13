import sqlite3
con = sqlite3.connect('data/pm.db')
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('TABLES:', cur.fetchall())
for t in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    name = t[0]
    print('=== TABLE', name, '===')
    cur.execute(f"PRAGMA table_info({name})")
    print('COLS:', cur.fetchall())
    cur.execute(f"SELECT COUNT(*) FROM {name}")
    print('ROWS:', cur.fetchone()[0])
