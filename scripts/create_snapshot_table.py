"""创建 daily_snapshot 表"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

sql = """
CREATE TABLE IF NOT EXISTS daily_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date DATE UNIQUE NOT NULL,
    account_type TEXT DEFAULT 'sim',
    total_asset REAL,
    total_market_value REAL,
    cash REAL,
    position_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

conn = sqlite3.connect(str(DB_PATH))
conn.execute(sql)
conn.commit()
conn.close()

print("✅ daily_snapshot 表创建成功")
