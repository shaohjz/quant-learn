import sqlite3

# Connect to pm.db
conn = sqlite3.connect('pm.db')
cursor = conn.cursor()

# Check what tables exist
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("Tables in pm.db:")
for table in tables:
    print(f"  - {table[0]}")

# If tasks table exists, check REQ-038
if any('tasks' in table for table in tables):
    cursor.execute("SELECT * FROM tasks WHERE id='REQ-038'")
    row = cursor.fetchone()
    if row:
        print(f"\nREQ-038 current status: {row}")
    else:
        print("\nREQ-038 not found in tasks table")
else:
    print("\nNo tasks table found. Checking all tables...")
    for table in tables:
        table_name = table[0]
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
        rows = cursor.fetchall()
        print(f"\n{table_name} sample data:")
        for row in rows:
            print(f"  {row}")

conn.close()
