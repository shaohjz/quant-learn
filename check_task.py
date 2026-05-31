import sqlite3

# Connect to pm.db
conn = sqlite3.connect('pm.db')
cursor = conn.cursor()

# Check current status of REQ-038
cursor.execute("SELECT * FROM tasks WHERE id='REQ-038'")
row = cursor.fetchone()
print("Current task status:")
print(row)

conn.close()
