#!/usr/bin/env python
"""初始化 watchlist_history 表"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS watchlist_history (
    code TEXT,
    name TEXT,
    category TEXT,
    added_at TEXT,
    added_by TEXT,
    added_reason TEXT,
    discovery_score REAL,
    metadata TEXT,
    PRIMARY KEY (code, added_at)
)
""")
conn.commit()

c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in c.fetchall()]
print("数据库表:", tables)
conn.close()
print("watchlist_history 表已创建")
