import sqlite3, sys
db = sys.argv[1] if len(sys.argv) > 1 else 'data/sim_live_mirror.db'
conn = sqlite3.connect(db)
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in c.fetchall()]
for t in tables:
    print('=' * 70)
    print('TABLE:', t)
    c.execute(f"PRAGMA table_info({t})")
    for col in c.fetchall():
        print(f'  {col[1]} {col[2]}')
    try:
        c.execute(f"SELECT COUNT(1) FROM {t}")
        print('  ROWS:', c.fetchone()[0])
    except Exception as e:
        print('  COUNT ERR:', e)
conn.close()
