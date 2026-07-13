import sqlite3, sys
conn = sqlite3.connect('data/pm.db')
c = conn.cursor()
mode = sys.argv[1] if len(sys.argv) > 1 else None

if mode == 'all':
    c.execute("SELECT id, title, priority, description, result_notes FROM tasks WHERE status='fixed' ORDER BY priority, updated_at")
    for r in c.fetchall():
        print('=' * 80)
        print('ID:', r[0], '| PRIORITY:', r[2])
        print('TITLE:', r[1])
        print('--- DESCRIPTION ---')
        print(r[3])
        print('--- RESULT_NOTES ---')
        print(r[4])
elif mode:
    c.execute("SELECT id, title, status, priority, description, updated_at, assigned_to, result_notes FROM tasks WHERE id=?", (mode,))
    r = c.fetchone()
    if r:
        cols = ['id', 'title', 'status', 'priority', 'description', 'updated_at', 'assigned_to', 'result_notes']
        for col, val in zip(cols, r):
            print(f'=== {col} ===')
            print(val)
    else:
        print('NOT FOUND', mode)
else:
    c.execute("SELECT id, title, status, priority FROM tasks WHERE status='fixed' ORDER BY priority, updated_at")
    for r in c.fetchall():
        print(r)
conn.close()
