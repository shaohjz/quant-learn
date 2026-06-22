#!/usr/bin/env python
"""检查模拟盘DB和PMDB的表结构"""
import sqlite3
import os

ROOT = "C:/Users/Administrator/.openclaw/workspace/quant-learn"

# 检查模拟盘DB
sim_db = f"{ROOT}/data/sim_live_mirror.db"
print(f"=== sim_live_mirror.db ===")
print(f"exists: {os.path.exists(sim_db)}")
if os.path.exists(sim_db):
    conn = sqlite3.connect(sim_db)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    print(f"tables: {tables}")
    for (t,) in tables:
        cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {count} rows, columns: {[c[1] for c in cols]}")
        if count > 0:
            sample = conn.execute(f"SELECT * FROM {t} LIMIT 2").fetchall()
            print(f"    sample: {sample}")
    conn.close()

# 检查PMDB
pm_db = f"{ROOT}/data/pm.db"
print(f"\n=== pm.db ===")
print(f"exists: {os.path.exists(pm_db)}")
if os.path.exists(pm_db):
    conn = sqlite3.connect(pm_db)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    print(f"tables: {tables}")
    for (t,) in tables:
        cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {count} rows, columns: {[c[1] for c in cols]}")
        if count > 0:
            sample = conn.execute(f"SELECT * FROM {t} LIMIT 2").fetchall()
            print(f"    sample: {sample}")
    conn.close()

print("\nDone.")
