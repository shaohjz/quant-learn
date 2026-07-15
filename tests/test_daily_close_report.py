"""收盘日报：当日盈亏必须相对昨日净值，禁止写死 10 万。"""

import sqlite3
from pathlib import Path

from scripts.daily_close_report import account_block, build_report


def _db(tmp: Path) -> Path:
    db = tmp / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sim_account (
            id INTEGER PRIMARY KEY, account_name TEXT,
            cash REAL, total_value REAL, initial_cash REAL
        );
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY, account_id INT, trade_date TEXT, trade_time TEXT,
            stock_code TEXT, stock_name TEXT, direction TEXT,
            price REAL, quantity INT, amount REAL, signal_reason TEXT
        );
        CREATE TABLE sim_positions (
            account_id INT, stock_code TEXT, stock_name TEXT, quantity INT,
            avg_cost REAL, current_price REAL, market_value REAL, pnl REAL, pnl_pct REAL
        );
        CREATE TABLE sim_daily_nav (
            account_id INT, trade_date TEXT, total_value REAL,
            PRIMARY KEY (account_id, trade_date)
        );
        """
    )
    conn.execute(
        "INSERT INTO sim_account VALUES (1,'learn',121992,219479.43,200000)"
    )
    conn.execute("INSERT INTO sim_daily_nav VALUES (1,'2026-07-14',219360.0)")
    conn.execute(
        "INSERT INTO sim_account VALUES (3,'swing_trade',100000,100000,100000)"
    )
    conn.execute("INSERT INTO sim_daily_nav VALUES (3,'2026-07-14',100000)")
    conn.commit()
    conn.close()
    return db


def test_day_pnl_not_vs_100k(tmp_path):
    db = _db(tmp_path)
    conn = sqlite3.connect(db)
    b = account_block(conn, 1, "模拟学习仓", "2026-07-15")
    conn.close()
    assert b["day_pnl"] is not None
    assert abs(b["day_pnl"] - 119.43) < 0.01
    assert abs(b["day_pct"]) < 1.0
    assert abs(b["cum_pnl"] - 19479.43) < 0.01


def test_report_mentions_both_accounts(tmp_path, monkeypatch):
    import scripts.daily_close_report as mod

    db = _db(tmp_path)
    monkeypatch.setattr(mod, "DB_PATH", db)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "output" / "swing_daily").mkdir(parents=True)
    md = build_report("2026-07-15", db_path=db)
    assert "模拟学习仓" in md
    assert "波段" in md
    assert "相对昨日净值" in md
    assert "+119,479" not in md
    assert "波段结论" in md
