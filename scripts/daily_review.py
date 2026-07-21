"""scripts/daily_review.py — 每日持仓复盘

重构说明 (QL-002):
  - 所有查询和打印逻辑移入 main() 函数
  - import 本模块不再连接数据库或产生输出
  - 支持通过命令行参数指定交易日
"""

import sys
import os
import io
import sqlite3
from datetime import datetime, date as DateType

# Windows GBK 兼容：强制 stdout 使用 UTF-8
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 只做 sys.path 设置，不连接数据库
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _resolve_db_path() -> str:
    """解析数据库路径（不打开连接）"""
    db_live = os.path.join(_PROJECT_ROOT, "data", "sim_live_mirror.db")
    db_default = os.path.join(_PROJECT_ROOT, "data", "sim.db")
    if os.path.exists(db_live):
        return db_live
    elif os.path.exists(db_default):
        return db_default
    else:
        from sim.db import DB_PATH
        return str(DB_PATH)


def main(trade_date: str | None = None):
    """执行每日复盘，打印账户、持仓、NAV、交易和止损信息。

    :param trade_date: 指定交易日字符串，如 '2026-07-10'；默认使用今天
    """
    db_path = _resolve_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    td = trade_date or DateType.today().isoformat()

    # 1. 账户信息
    print("=== 账户信息 ===")
    cur.execute("SELECT * FROM sim_account")
    accounts = cur.fetchall()
    for a in accounts:
        print(dict(a))

    # 2. 当前持仓
    print("\n=== 当前持仓 ===")
    cur.execute("SELECT * FROM sim_positions")
    positions = cur.fetchall()
    for p in positions:
        print(dict(p))

    # 3. 最近交易日NAV
    print(f"\n=== 最近NAV（最近10条）===")
    cur.execute("SELECT * FROM sim_daily_nav ORDER BY trade_date DESC LIMIT 10")
    navs = cur.fetchall()
    for n in navs:
        print(dict(n))

    # 4. 今日交易
    print(f"\n=== 今日交易 {td} ===")
    cur.execute("SELECT * FROM sim_trades WHERE trade_date = ?", (td,))
    trades = cur.fetchall()
    if trades:
        for t in trades:
            print(dict(t))
    else:
        print("(无今日交易)")

    # 5. 最近交易
    print("\n=== 最近交易（最近10条）===")
    cur.execute("SELECT * FROM sim_trades ORDER BY trade_date DESC, id DESC LIMIT 10")
    recent_trades = cur.fetchall()
    for t in recent_trades:
        print(dict(t))

    # 6. 持仓盈亏分析
    print("\n=== 持仓盈亏分析 ===")
    cur.execute("""
        SELECT sp.*, 
               (sp.current_price - sp.avg_cost) as price_diff,
               CASE WHEN sp.avg_cost > 0 THEN (sp.current_price - sp.avg_cost)/sp.avg_cost*100 ELSE 0 END as pct_change
        FROM sim_positions sp
    """)
    for row in cur.fetchall():
        d = dict(row)
        print(f"{d['stock_code']} {d['stock_name']}: 数量={d['quantity']} 成本={d['avg_cost']:.2f} 现价={d['current_price']:.2f} 浮盈={d['pnl']:.2f}({d['pnl_pct']:.2f}%) trailing_stop={d.get('trailing_stop_price', 'N/A')} highest={d.get('highest_price', 'N/A')}")

    # 7. 止损/止盈检查
    print("\n=== 止损/止盈检查 ===")
    cur.execute("SELECT * FROM sim_positions WHERE trailing_stop_price IS NOT NULL")
    for row in cur.fetchall():
        d = dict(row)
        cp = d['current_price']
        tsp = d['trailing_stop_price']
        if cp <= tsp:
            print(f"⚠️ {d['stock_code']} {d['stock_name']}: 当前价{cp:.2f} 已触发移动止损{tsp:.2f}！")
        else:
            print(f"✅ {d['stock_code']} {d['stock_name']}: 当前价{cp:.2f} 止损价{tsp:.2f} 距离{((cp-tsp)/cp*100):.2f}%")

    conn.close()


if __name__ == "__main__":
    td_arg = sys.argv[1] if len(sys.argv) > 1 else None
    main(trade_date=td_arg)
