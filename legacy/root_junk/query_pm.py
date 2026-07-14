import sqlite3

conn = sqlite3.connect('data/pm.db')
cur = conn.cursor()

# Status counts
cur.execute('SELECT status, COUNT(*) FROM tasks GROUP BY status')
print('=== STATUS COUNTS ===')
for row in cur.fetchall():
    print('  {}: {}'.format(row[0], row[1]))

# This week's updated tasks
cur.execute("SELECT id, type, title, status, priority, assigned_to, updated_at FROM tasks WHERE updated_at >= '2026-06-30' ORDER BY updated_at DESC")
print('\n=== TASKS UPDATED THIS WEEK (Jun 30 - Jul 3) ===')
for row in cur.fetchall():
    print('  [{}] {} | {} | P{} | {} | updated={}'.format(row[3], row[0], row[1], row[4], row[2][:50], row[6][:10]))

# Open/pending/blocked
cur.execute("SELECT id, type, title, status, priority, assigned_to FROM tasks WHERE status IN ('blocked', 'open', 'pending') ORDER BY priority, id")
print('\n=== OPEN / PENDING / BLOCKED TASKS ===')
for row in cur.fetchall():
    print('  [{}] {} | {} | P{} | {}'.format(row[3], row[0], row[1], row[4], row[2][:60]))

# In progress
cur.execute("SELECT id, type, title, status, priority, assigned_to FROM tasks WHERE status = 'in_progress' ORDER BY priority, id")
print('\n=== IN PROGRESS TASKS ===')
for row in cur.fetchall():
    print('  [{}] {} | {} | P{} | {} | assignee={}'.format(row[3], row[0], row[1], row[4], row[2][:50], row[5]))

conn.close()
