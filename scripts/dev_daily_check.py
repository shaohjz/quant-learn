"""研发经理每日检查脚本 - 检查PM数据库和模拟盘数据库"""
import sqlite3
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

def check_pm_db():
    db = sqlite3.connect(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\pm.db')
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"=== PM DB Tables: {tables} ===")
    for t in tables:
        cur.execute(f'SELECT * FROM "{t}"')
        rows = cur.fetchall()
        print(f'\n--- {t} ({len(rows)} rows) ---')
        for r in rows:
            d = dict(r)
            print(json.dumps(d, ensure_ascii=False, default=str))
    db.close()

def check_sim_db():
    db = sqlite3.connect(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db')
    db.row_factory = sqlite3.Row
    cur = db.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"\n=== Sim DB Tables: {tables} ===")
    for t in tables:
        cur.execute(f'SELECT COUNT(*) as cnt FROM "{t}"')
        cnt = cur.fetchone()[0]
        print(f'{t}: {cnt} rows')
        if cnt <= 10:
            cur.execute(f'SELECT * FROM "{t}" LIMIT 5')
            for r in cur.fetchall():
                d = dict(r)
                print(' ', json.dumps(d, ensure_ascii=False, default=str))
    db.close()

def check_bugs():
    import os
    bugs_dir = r'C:\Users\Administrator\.openclaw\workspace\quant-learn\pm\bugs'
    if os.path.exists(bugs_dir):
        files = os.listdir(bugs_dir)
        print(f"\n=== Bug Reports ({len(files)} files) ===")
        for f in files:
            print(f'  {f}')

if __name__ == '__main__':
    check_pm_db()
    check_sim_db()
    check_bugs()
