import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.daily_review_vnpy import fetch_unmatched_sell_confirmations


def test_fetch_unmatched_sell_confirmations(tmp_path):
    db = tmp_path / "sim.db"
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE threshold_state (
            id INTEGER PRIMARY KEY,
            stock_code TEXT,
            stock_name TEXT,
            rule_name TEXT,
            rule_threshold REAL,
            status TEXT,
            next_day_confirmed_at TEXT,
            next_day_price REAL,
            updated_at TEXT,
            notes TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY,
            account_id INTEGER,
            stock_code TEXT,
            trade_date TEXT,
            direction TEXT
        )
    """)
    conn.execute("""
        INSERT INTO threshold_state
        (stock_code, stock_name, rule_name, rule_threshold, status,
         next_day_confirmed_at, next_day_price, updated_at, notes)
        VALUES ('603757', '大元泵业', 'trend_break', 56.77, 'executed',
                '2026-05-27', 55.01, '2026-05-27 15:05:16', '执行卖单')
    """)
    conn.commit()

    rows = fetch_unmatched_sell_confirmations("2026-05-27", db)
    assert len(rows) == 1
    assert rows[0]["stock_code"] == "603757"

    conn.execute("""
        INSERT INTO sim_trades (account_id, stock_code, trade_date, direction)
        VALUES (1, '603757', '2026-05-27', 'SELL')
    """)
    conn.commit()
    conn.close()

    rows = fetch_unmatched_sell_confirmations("2026-05-27", db)
    assert rows == []
