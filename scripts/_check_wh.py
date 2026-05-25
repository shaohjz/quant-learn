import sqlite3
conn = sqlite3.connect('data/sim_live_mirror.db')
conn.row_factory = sqlite3.Row
cols = [r[1] for r in conn.execute('PRAGMA table_info(watchlist_history)').fetchall()]
print('columns:', cols)
print()
rows = conn.execute('SELECT * FROM watchlist_history LIMIT 5').fetchall()
for r in rows:
    d = dict(r)
    print(f"  {d.get('code')} {d.get('name')} category={d.get('category')} score={d.get('discovery_score')}")
    print(f"    added={d.get('added_at')} signal={d.get('signal_type','')}")
conn.close()
