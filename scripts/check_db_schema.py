"""检查数据库 schema：review_decisions 表、sim_positions 表"""
import sqlite3
import os

ROOT = os.path.dirname(os.path.abspath(__file__)) + '/..'
paths = [
    ('data/sim_live_mirror.db', os.path.join(ROOT, 'data/sim_live_mirror.db')),
    ('data/sim.db', os.path.join(ROOT, 'data/sim.db')),
    ('data/pm.db', os.path.join(ROOT, 'data/pm.db')),
]

for label, p in paths:
    if os.path.exists(p):
        print(f'Found: {label} -> {p}')
        conn = sqlite3.connect(p)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        print(f'  tables: {tables}')
        for t in ['review_decisions', 'sim_positions', 'sim_account', 'sim_trades']:
            if t in tables:
                cols = conn.execute(f'PRAGMA table_info([{t}])').fetchall()
                print(f'  {t}: {[(c[1], c[2]) for c in cols]}')
        conn.close()
    else:
        print(f'NOT found: {label}')
