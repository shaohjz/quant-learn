import sqlite3
con = sqlite3.connect('data/pm.db')
cur = con.cursor()

print('===== PENDING (active, not started) =====')
cur.execute("SELECT id, type, title, priority, assigned_to, created_at, updated_at, description FROM tasks WHERE status='pending'")
for r in cur.fetchall():
    print(f'\n[{r[0]}] type={r[1]} prio={r[3]} @={r[4]}')
    print(f'  title: {r[2]}')
    print(f'  created={r[5]} updated={r[6]}')
    if r[7]: print(f'  desc: {r[7][:300]}')

print('\n\n===== TESTING (implemented, awaiting verification) =====')
cur.execute("SELECT id, type, title, priority, assigned_to, updated_at, work_notes, result_notes FROM tasks WHERE status='testing' ORDER BY priority, updated_at")
for r in cur.fetchall():
    print(f'\n[{r[0]}] type={r[1]} prio={r[3]} @={r[4]} upd={r[5]}')
    print(f'  title: {r[2]}')
    if r[6]: print(f'  work_notes: {r[6][:200]}')
    if r[7]: print(f'  result_notes: {r[7][:200]}')

print('\n\n===== FRESHNESS ALERTS =====')
cur.execute("SELECT id, check_time, source, ok, age_hours, latest_ts, threshold_hours, message FROM freshness_alerts ORDER BY id")
for r in cur.fetchall():
    print(f'[{r[0]}] {r[1]} src={r[2]} ok={r[3]} age={r[4]}h th={r[5]}h latest={r[4]}')
    print(f'   msg: {r[7]}')
