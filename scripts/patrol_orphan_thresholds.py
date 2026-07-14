"""
REQ-058 巡检脚本：每日检查并清理 threshold_state 中的悬挂记录。
当 sim_positions 中某标的 quantity=0 但 threshold_state 仍有活跃记录时自动清理。
"""
import sqlite3
from pathlib import Path
from datetime import date

DB = Path(__file__).resolve().parents[1] / 'data' / 'sim_live_mirror.db'

def patrol():
    conn = sqlite3.connect(str(DB))
    cur = conn.cursor()
    
    # 检查表存在
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if 'threshold_state' not in tables or 'sim_positions' not in tables:
        conn.close()
        return 0
    
    # 查找孤儿记录
    orphan_count = cur.execute("""
        SELECT COUNT(*) FROM threshold_state ts
        LEFT JOIN sim_positions sp ON ts.stock_code = sp.stock_code AND sp.account_id = 1
        WHERE (sp.quantity = 0 OR sp.quantity IS NULL)
          AND ts.status IN ('pending', 'armed', 'confirmed')
    """).fetchone()[0]
    
    if orphan_count > 0:
        cur.execute("""
            UPDATE threshold_state SET status = 'expired', updated_at = CURRENT_TIMESTAMP
            WHERE id IN (
                SELECT ts.id FROM threshold_state ts
                LEFT JOIN sim_positions sp ON ts.stock_code = sp.stock_code AND sp.account_id = 1
                WHERE (sp.quantity = 0 OR sp.quantity IS NULL)
                  AND ts.status IN ('pending', 'armed', 'confirmed')
            )
        """)
        conn.commit()
        print(f"[{date.today()}] Cleaned {orphan_count} orphan threshold_state record(s)")
    else:
        print(f"[{date.today()}] No orphan records found")
    
    conn.close()
    return orphan_count

if __name__ == '__main__':
    patrol()
