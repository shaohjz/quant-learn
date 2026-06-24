import sqlite3

conn = sqlite3.connect('data/pm.db')
c = conn.cursor()

# Get REQ-049 full details
c.execute("SELECT * FROM tasks WHERE id = ?", ("REQ-049",))
row = c.fetchone()
if row:
    cols = [desc[0] for desc in c.description]
    print("REQ-049 full details:")
    for col, val in zip(cols, row):
        print(f"\n=== {col} ===")
        print(val)
else:
    print("REQ-049 not found")

# Also get REQ-046 details (second highest P0)
c.execute("SELECT * FROM tasks WHERE id = ?", ("REQ-046",))
row = c.fetchone()
if row:
    cols = [desc[0] for desc in c.description]
    print("\n\nREQ-046 full details:")
    for col, val in zip(cols, row):
        print(f"\n=== {col} ===")
        print(val)

conn.close()
