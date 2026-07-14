"""交易台账：汇总渲染与空库/有成交。"""

import sqlite3
from pathlib import Path

from scripts.trade_journal import collect_journal, render_markdown, write_journal


def _make_db(tmp: Path) -> Path:
    db = tmp / "t.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sim_account (
            id INTEGER PRIMARY KEY,
            account_name TEXT,
            cash REAL,
            total_value REAL,
            initial_cash REAL
        );
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY,
            account_id INTEGER,
            trade_date TEXT,
            trade_time TEXT,
            stock_code TEXT,
            stock_name TEXT,
            direction TEXT,
            price REAL,
            quantity INTEGER,
            amount REAL,
            commission REAL,
            signal_reason TEXT
        );
        CREATE TABLE sim_positions (
            account_id INTEGER,
            stock_code TEXT,
            stock_name TEXT,
            quantity INTEGER,
            avg_cost REAL,
            current_price REAL,
            market_value REAL,
            pnl REAL,
            pnl_pct REAL,
            trailing_stop_price REAL
        );
        CREATE TABLE sim_daily_nav (
            account_id INTEGER,
            trade_date TEXT,
            total_value REAL,
            cash REAL,
            market_value REAL,
            PRIMARY KEY (account_id, trade_date)
        );
        """
    )
    conn.execute(
        "INSERT INTO sim_account VALUES (3,'swing_trade',90000,100500,100000)"
    )
    conn.execute(
        "INSERT INTO sim_daily_nav VALUES (3,'2026-07-13',100000,100000,0)"
    )
    conn.execute(
        "INSERT INTO sim_daily_nav VALUES (3,'2026-07-14',100500,90000,10500)"
    )
    conn.execute(
        "INSERT INTO sim_trades (account_id,trade_date,trade_time,stock_code,stock_name,"
        "direction,price,quantity,amount,commission,signal_reason) "
        "VALUES (3,'2026-07-14','14:30:00','600900','长江电力','BUY',28,300,8400,5,'A分7')"
    )
    conn.execute(
        "INSERT INTO sim_positions VALUES (3,'600900','长江电力',300,28,35,10500,2100,25,26.6)"
    )
    conn.commit()
    conn.close()
    return db


def test_collect_and_render(tmp_path):
    db = _make_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    j = collect_journal(conn, "2026-07-14", db_path=db)
    conn.close()
    assert j["totals"]["trades"] == 1
    acc = j["accounts"][0]
    assert acc["label"] == "swing_trade"
    assert acc["trade_count"] == 1
    assert abs(acc["day_pnl"] - 500) < 0.01
    md = render_markdown(j)
    assert "交易台账 2026-07-14" in md
    assert "600900" in md
    assert "复盘备注" in md


def test_write_preserves_notes(tmp_path, monkeypatch):
    import scripts.trade_journal as tj

    monkeypatch.setattr(tj, "PM_OUT", tmp_path / "pm")
    monkeypatch.setattr(tj, "OUT_MIRROR", tmp_path / "out")
    db = _make_db(tmp_path)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    j = collect_journal(conn, "2026-07-14", db_path=db)
    conn.close()
    md = render_markdown(j)
    p, _, _ = write_journal(j, md)
    text = p.read_text(encoding="utf-8")
    text = text.replace("- 今日做对了什么：", "- 今日做对了什么：买点执行好")
    p.write_text(text, encoding="utf-8")
    write_journal(j, md)
    again = p.read_text(encoding="utf-8")
    assert "买点执行好" in again
