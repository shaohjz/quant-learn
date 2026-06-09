import sqlite3

conn = sqlite3.connect('data/pm.db')
cursor = conn.cursor()

# Count by status
cursor.execute('SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status')
status_counts = cursor.fetchall()

# Count by priority
cursor.execute('SELECT priority, COUNT(*) as cnt FROM tasks GROUP BY priority')
pri_counts = cursor.fetchall()

# Count by type
cursor.execute('SELECT type, COUNT(*) as cnt FROM tasks GROUP BY type')
type_counts = cursor.fetchall()

print('=== STATUS ===')
for r in status_counts:
    print(r[0], r[1])
print('=== PRIORITY ===')
for r in pri_counts:
    print(r[0], r[1])
print('=== TYPE ===')
for r in type_counts:
    print(r[0], r[1])

# In progress tasks
cursor.execute("SELECT id, type, title, priority, assigned_to FROM tasks WHERE status='in_progress' ORDER BY priority")
print('=== IN_PROGRESS ===')
for r in cursor.fetchall():
    print(r[0], '|', r[1], '|', r[2][:50], '|', r[3], '|', r[4] or '')

# Testing tasks
cursor.execute("SELECT id, type, title, priority, assigned_to FROM tasks WHERE status='testing' ORDER BY priority")
print('=== TESTING ===')
for r in cursor.fetchall():
    print(r[0], '|', r[1], '|', r[2][:50], '|', r[3], '|', r[4] or '')

# Blocked tasks
cursor.execute("SELECT id, type, title, priority, assigned_to FROM tasks WHERE status='blocked' ORDER BY priority")
print('=== BLOCKED ===')
for r in cursor.fetchall():
    print(r[0], '|', r[1], '|', r[2][:50], '|', r[3], '|', r[4] or '')

# Done this week (2026-06-01 onwards)
cursor.execute("SELECT id, type, title, priority FROM tasks WHERE status='done' AND updated_at >= '2026-06-01' ORDER BY priority")
print('=== DONE THIS WEEK ===')
for r in cursor.fetchall():
    print(r[0], '|', r[1], '|', r[2][:50], '|', r[3])

conn.close()
