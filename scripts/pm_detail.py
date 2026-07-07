import sqlite3
con=sqlite3.connect("data/pm.db"); con.row_factory=sqlite3.Row; cur=con.cursor()
for tid in ['REQ-057','REQ-048','REQ-043','REQ-045','REQ-092','TASK-20260701-200653-001','REQ-011','REQ-059','REQ-060']:
    cur.execute("SELECT id,status,priority,assigned_to,result_notes,work_notes,updated_at FROM tasks WHERE id=?",(tid,))
    r=cur.fetchone()
    if r:
        print(f"\n### {r['id']} [{r['status']}/{r['priority']}] @{r['assigned_to']} upd={r['updated_at']}")
        print("  result_notes:", (r['result_notes'] or '')[:400])
        print("  work_notes:", (r['work_notes'] or '')[:500])
con.close()
