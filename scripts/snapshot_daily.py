"""
每日快照脚本 - 记录账户资产状态
用途: 记录每日收盘后的账户资产，为收益率曲线提供数据
"""
import sqlite3
import sys
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "sim_live_mirror.db"

def get_account_snapshot(conn, account_type='sim'):
    """获取账户快照数据"""
    # 获取现金
    cash_row = conn.execute(
        "SELECT cash FROM sim_account WHERE id=1"
    ).fetchone()
    cash = cash_row[0] if cash_row else 0
    
    # 获取持仓总市值
    positions = conn.execute(
        "SELECT stock_code, quantity, avg_cost FROM sim_positions WHERE account_id=1 AND quantity > 0"
    ).fetchall()
    
    total_market_value = 0
    for code, qty, cost in positions:
        # 使用成本价作为市值（收盘后可以获取真实行情价）
        # TODO: 可以集成实时行情API获取收盘价
        total_market_value += qty * cost
    
    total_asset = cash + total_market_value
    position_count = len(positions)
    
    return {
        'total_asset': total_asset,
        'total_market_value': total_market_value,
        'cash': cash,
        'position_count': position_count
    }

def save_snapshot(snapshot_date=None):
    """保存每日快照"""
    if snapshot_date is None:
        snapshot_date = date.today().isoformat()
    
    conn = sqlite3.connect(str(DB_PATH))
    
    try:
        # 获取快照数据
        snapshot = get_account_snapshot(conn, 'sim')
        
        # 插入或更新
        conn.execute("""
            INSERT INTO daily_snapshot (
                snapshot_date, account_type, total_asset, 
                total_market_value, cash, position_count
            ) VALUES (?, 'sim', ?, ?, ?, ?)
            ON CONFLICT(snapshot_date) DO UPDATE SET
                total_asset=excluded.total_asset,
                total_market_value=excluded.total_market_value,
                cash=excluded.cash,
                position_count=excluded.position_count,
                created_at=CURRENT_TIMESTAMP
        """, (
            snapshot_date,
            snapshot['total_asset'],
            snapshot['total_market_value'],
            snapshot['cash'],
            snapshot['position_count']
        ))
        
        conn.commit()
        
        print(f"✅ 快照已保存: {snapshot_date}")
        print(f"   总资产: {snapshot['total_asset']:.2f}")
        print(f"   现金: {snapshot['cash']:.2f}")
        print(f"   市值: {snapshot['total_market_value']:.2f}")
        print(f"   持仓数: {snapshot['position_count']}")
        
    except Exception as e:
        print(f"❌ 保存快照失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
    
    return True

if __name__ == '__main__':
    # 可以通过命令行参数指定日期: python snapshot_daily.py 2026-05-25
    snapshot_date = sys.argv[1] if len(sys.argv) > 1 else None
    save_snapshot(snapshot_date)
