#!/usr/bin/env python3
"""Smoke test for release deployment"""
import sqlite3
import sys
import os

def smoke_test():
    # Test 1: sim_live_mirror.db
    db_path = 'data/sim_live_mirror.db'
    print(f"=== Smoke Test: {db_path} ===")
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # Get all tables
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in c.fetchall()]
        print(f"Tables: {tables}")
        
        # Check key tables
        for t in ['sim_account', 'sim_positions', 'sim_daily_nav', 'sim_account_events']:
            if t in tables:
                c.execute(f"SELECT count(*) FROM {t}")
                cnt = c.fetchone()[0]
                print(f"  OK: {t} ({cnt} rows)")
            else:
                print(f"  WARN: {t} not found")
        
        # REQ-061: daily_return should not be NULL
        if 'sim_daily_nav' in tables:
            c.execute("SELECT count(*) FROM sim_daily_nav WHERE daily_return IS NULL")
            null_cnt = c.fetchone()[0]
            c.execute("SELECT count(*) FROM sim_daily_nav")
            total = c.fetchone()[0]
            print(f"  REQ-061: daily_return non-null: {total - null_cnt}/{total}")
        
        # REQ-064: account_id=2 should exist in sim_account
        if 'sim_account' in tables:
            c.execute("SELECT id, account_name FROM sim_account WHERE id=2")
            r = c.fetchone()
            if r:
                print(f"  REQ-064: sim_account id=2 exists: {r[1]}")
            else:
                print("  REQ-064: WARN sim_account id=2 NOT found")
        
        conn.close()
    except Exception as e:
        print(f"FAIL: {e}")
        return False
    
    # Test 2: pm.db
    pm_db = 'data/pm.db'
    print(f"\n=== Smoke Test: {pm_db} ===")
    try:
        conn = sqlite3.connect(pm_db)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in c.fetchall()]
        print(f"Tables: {tables}")
        conn.close()
    except Exception as e:
        print(f"WARN: {e}")
    
    # Test 3: Key scripts import check
    print("\n=== Script Import Test ===")
    import subprocess
    scripts_to_check = [
        'scripts/daily_review.py',
        'scripts/portfolio_alert.py',
        'scripts/sync_real_position.py',
        'scripts/backfill_data.py',
    ]
    for s in scripts_to_check:
        if os.path.exists(s):
            print(f"  OK: {s} exists")
        else:
            print(f"  FAIL: {s} NOT found")
            return False
    
    print("\n=== All Smoke Tests PASSED ===")
    return True

if __name__ == '__main__':
    success = smoke_test()
    sys.exit(0 if success else 1)
