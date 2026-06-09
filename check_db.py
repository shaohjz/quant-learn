import sqlite3
from pathlib import Path

ROOT = Path('.').resolve()
db = ROOT / 'data' / 'sim_live_mirror.db'
print('DB exists:', db.exists())
conn = sqlite3.connect(str(db))
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('Tables:', [t[0] for t in tables])
conn.close()
