import sqlite3
import json

conn = sqlite3.connect('data/pm.db')
c = conn.cursor()

# Check schema
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Tables:", c.fetchall())

# Get REQ-049 details
c.execute("SELECT * FROM requirements WHERE id = ?", ("REQ-049",))
row = c.fetchone()
if row:
    cols = [desc[0] for desc in c.description]
    print("\nREQ-049:")
    for col, val in zip(cols, row):
        print(f"  {col}: {val}")
else:
    print("REQ-049 not found")

# Get all in_progress P0 items
print("\n\nAll in_progress items:")
c.execute("SELECT id, title, status, priority FROM requirements WHERE status = 'in_progress' ORDER BY priority")
for row in c.fetchall():
    print(f"  {row[0]} ({row[2]}) [{row[3]}]: {row[1]}")

# Get all open items  
print("\n\nAll open items:")
c.execute("SELECT id, title, status, priority FROM requirements WHERE status = 'open' ORDER BY priority")
for row in c.fetchall():
    print(f"  {row[0]} ({row[2]}) [{row[3]}]: {row[1]}")

conn.close()
