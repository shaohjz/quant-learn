"""
vqlearn/services/multi_strategy_shadow.py

多策略 shadow 跟踪（不下单，只记录信号）。

目的：实盘期间让 5 个策略并行跑，记录每个策略的虚拟信号到 db，
后续可以对比"如果当天用这个策略，会发生什么"，积累实盘 vs 回测对比数据。

每个 tick 调一次：
  1. 拉今日 + 历史 K 线
  2. 每个策略 decide → Signal
  3. 记录到 strategy_shadow_signals 表
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import sqlite3
import logging
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / 'data' / 'sim_live_mirror.db'

logger = logging.getLogger(__name__)


def init_shadow_table():
    """创建 shadow 信号表（如果不存在）"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_shadow_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_date TEXT NOT NULL,
            shadow_time TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            price REAL NOT NULL,
            position INTEGER DEFAULT 0,
            signal_action TEXT NOT NULL,
            signal_rule TEXT,
            signal_reason TEXT,
            confidence REAL DEFAULT 1.0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_shadow_date ON strategy_shadow_signals(shadow_date, strategy_id)
    """)
    conn.commit()
    conn.close()


def record_shadow_signal(strategy_id: str, code: str, name: str, price: float,
                         position: int, signal) -> None:
    """记录一条 shadow 信号到 db"""
    if signal.action == 'NO_ACTION':
        return  # 不记录无信号

    conn = sqlite3.connect(str(DB_PATH))
    now = datetime.now()
    conn.execute("""
        INSERT INTO strategy_shadow_signals
        (shadow_date, shadow_time, strategy_id, stock_code, stock_name,
         price, position, signal_action, signal_rule, signal_reason, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        now.strftime('%Y-%m-%d'),
        now.strftime('%H:%M:%S'),
        strategy_id, code, name,
        price, position,
        signal.action, signal.rule_name, signal.reason, signal.confidence,
    ))
    conn.commit()
    conn.close()


def get_today_shadow_summary() -> pd.DataFrame:
    """取今天所有 shadow 信号的汇总"""
    conn = sqlite3.connect(str(DB_PATH))
    today = datetime.now().strftime('%Y-%m-%d')
    df = pd.read_sql_query("""
        SELECT strategy_id, stock_code, stock_name, signal_action,
               COUNT(*) as count, MIN(price) as min_price, MAX(price) as max_price
        FROM strategy_shadow_signals
        WHERE shadow_date = ?
        GROUP BY strategy_id, stock_code, signal_action
        ORDER BY strategy_id, stock_code
    """, conn, params=(today,))
    conn.close()
    return df


if __name__ == '__main__':
    init_shadow_table()
    print(f'✅ shadow 表已就绪: {DB_PATH}')

    # 显示今日 summary
    df = get_today_shadow_summary()
    if df.empty:
        print('📭 今日尚无 shadow 信号')
    else:
        print(df.to_string())
