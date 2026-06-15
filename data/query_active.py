import sqlite3

conn = sqlite3.connect('data/pm.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

sql = (
    "SELECT id, status, priority, title, assigned_to, updated_at "
    "FROM tasks "
    "WHERE status NOT IN ('done','fixed','verified') "
    "ORDER BY priority, id"
)
cur.execute(sql)
rows = cur.fetchall()

print("=== ACTIVE TASKS (not done/fixed/verified) ===")
for r in rows:
    tid = r['id']
    status = r['status']
    pri = r['priority']
    title = r['title'][:60]
    assigned = r['assigned_to'] if r['assigned_to'] else '-'
    updated = r['updated_at'][:10]
    print(f"{tid} | {status} | P{pri} | {title} | {assigned} | {updated}")

conn.close()
