#!/usr/bin/env python3
"""
migration_add_sector_to_positions.py — REQ-036 数据库迁移
给 sim_positions 表添加 sector / industry 字段，用于行业集中度风控。
"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

def migrate():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        # 检查字段是否已存在
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sim_positions)").fetchall()]
        migrations = []

        if 'sector' not in cols:
            migrations.append("ALTER TABLE sim_positions ADD COLUMN sector TEXT DEFAULT ''")
        if 'industry' not in cols:
            migrations.append("ALTER TABLE sim_positions ADD COLUMN industry TEXT DEFAULT ''")

        if not migrations:
            print("✅ sim_positions 已有 sector/industry 字段，无需迁移")
            return

        for sql in migrations:
            print(f"  ⟳ 执行: {sql}")
            conn.execute(sql)
        conn.commit()
        print(f"✅ 迁移完成，已添加: {[m.split('ADD COLUMN ')[1].split()[0] for m in migrations]}")
    except Exception as e:
        conn.rollback()
        print(f"❌ 迁移失败: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
