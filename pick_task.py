import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data' / 'pm.db'
conn = sqlite3.connect(DB)
cursor = conn.cursor()
cursor.execute('''
    SELECT id, type, title, description, status, priority
    FROM tasks
    WHERE status = "pending"
    ORDER BY CASE priority 
        WHEN "P0" THEN 1 
        WHEN "P1" THEN 2 
        WHEN "P2" THEN 3 
        WHEN "P3" THEN 4
        ELSE 5 
    END 
    LIMIT 1
''')
row = cursor.fetchone()
if row:
    print(f"ID: {row[0]}")
    print(f"Type: {row[1]}")
    print(f"Title: {row[2]}")
    print(f"Description: {row[3]}")
    print(f"Status: {row[4]}")
    print(f"Priority: {row[5]}")
else:
    print("No pending tasks found")
conn.close()
