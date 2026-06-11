import sqlite3

db_path = 'data/pm.db'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

ids = ['REQ-038', 'REQ-036', 'REQ-035', 'REQ-034', 'REQ-033', 'REQ-041', 'REQ-032']
for tid in ids:
    row = conn.execute('SELECT * FROM tasks WHERE id = ?', (tid,)).fetchone()
    if row:
        d = dict(row)
        print(f"{d['id']} | {d['status']} | {d['priority']} | {d['title']}")
        print(f"  desc: {d['description'][:200]}")
    else:
        print(f"{tid}: not found")

conn.close()
