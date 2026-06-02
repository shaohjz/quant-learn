import sqlite3
import os

db_path = "data/pm.db"
print(f"Checking {db_path}")
print(f"Exists: {os.path.exists(db_path)}")

if os.path.exists(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"Tables: {tables}")
        
        if tables:
            cursor.execute("SELECT * FROM tasks")
            rows = cursor.fetchall()
            print(f"Number of tasks: {len(rows)}")
            for row in rows:
                print(row)
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
