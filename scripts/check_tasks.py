import sqlite3
conn = sqlite3.connect(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db")
cur = conn.cursor()
cur.execute("SELECT id, type, title, status, priority, updated_at FROM tasks WHERE status NOT IN ('done','verified') OR updated_at >= '2026-07-01' ORDER BY updated_at DESC")
rows = cur.fetchall()
for r in rows:
    print(r)
conn.close()
