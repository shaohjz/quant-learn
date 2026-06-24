import sqlite3

conn = sqlite3.connect('data/pm.db')
c = conn.cursor()

# Get all actionable items (pending, in_progress, open)
c.execute("SELECT id, title, status, priority, type FROM tasks WHERE status IN ('pending', 'in_progress', 'open') ORDER BY priority, id")
rows = c.fetchall()
print("Actionable items (pending/in_progress/open):")
for row in rows:
    print(f"  {row[0]} ({row[2]}) [{row[3]}] ({row[4]}): {row[1]}")

print("\n\nAll testing/fixed items (P0/S0/S1):")
c.execute("SELECT id, title, status, priority, type FROM tasks WHERE status IN ('testing', 'fixed') AND (priority LIKE 'P0%' OR priority LIKE 'S%') ORDER BY priority, id")
rows = c.fetchall()
for row in rows:
    print(f"  {row[0]} ({row[2]}) [{row[3]}] ({row[4]}): {row[1]}")

conn.close()
