#!/usr/bin/env python
"""
幂等 migration runner — 为 watchlist_history 添加缺少的 removed_at / removed_reason 列。
只添加不存在的列，多次运行安全。
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

MISSING_COLS = {
    "removed_at": "TEXT",
    "removed_reason": "TEXT",
}

def migrate():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # 获取当前 watchlist_history 的所有列
    existing_cols = set(
        r[1] for r in c.execute("PRAGMA table_info(watchlist_history)").fetchall()
    )

    added = []
    for col_name, col_type in MISSING_COLS.items():
        if col_name not in existing_cols:
            c.execute(f'ALTER TABLE watchlist_history ADD COLUMN {col_name} {col_type}')
            added.append(col_name)

    conn.commit()
    conn.close()

    if added:
        print(f"✅ 已添加列: {', '.join(added)}")
    else:
        print("✅ 所有列已存在，无需迁移")

if __name__ == "__main__":
    migrate()
