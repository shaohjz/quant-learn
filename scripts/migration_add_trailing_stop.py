"""P2: \u8ddf\u8e2a\u6b62\u635f \u2014 \u7ed9 sim_positions \u52a0 trailing_stop_price \u5b57\u6bb5\u3002

\u6dfb\u52a0\u5b57\u6bb5\uff1a
- trailing_stop_price REAL DEFAULT NULL  \u2014 \u5f53\u524d\u7684\u8ddf\u8e2a\u6b62\u635f\u4ef7
- highest_price REAL DEFAULT NULL        \u2014 \u6301\u4ed3\u671f\u95f4\u521b\u8fc7\u7684\u6700\u9ad8\u4ef7\uff08\u7528\u4e8e\u8ba1\u7b97\u8ddf\u8e2a\u4f4d\uff09
"""
import sqlite3
from pathlib import Path

DBS = [
    Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db'),
    Path(r'C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim.db'),
]

for db_path in DBS:
    if not db_path.exists():
        print(f'skip (not exist): {db_path}')
        continue
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cols = [c[1] for c in cur.execute("PRAGMA table_info(sim_positions)").fetchall()]
    print(f'\n{db_path.name}: existing cols = {cols}')
    
    if 'trailing_stop_price' not in cols:
        cur.execute("ALTER TABLE sim_positions ADD COLUMN trailing_stop_price REAL DEFAULT NULL")
        print('  + added trailing_stop_price')
    else:
        print('  trailing_stop_price exists')
    
    if 'highest_price' not in cols:
        cur.execute("ALTER TABLE sim_positions ADD COLUMN highest_price REAL DEFAULT NULL")
        print('  + added highest_price')
    else:
        print('  highest_price exists')
    
    # \u521d\u59cb\u5316\u5df2\u6709\u6301\u4ed3\u7684 highest_price = max(avg_cost, current_price)
    cur.execute("""UPDATE sim_positions 
                   SET highest_price = MAX(avg_cost, current_price)
                   WHERE highest_price IS NULL AND quantity > 0""")
    affected = cur.rowcount
    print(f'  initialized highest_price for {affected} positions')
    
    conn.commit()
    conn.close()

print('\nDone.')
