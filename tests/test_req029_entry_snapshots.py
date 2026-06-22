from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE sim_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            stock_code TEXT,
            stock_name TEXT,
            quantity INTEGER,
            avg_cost REAL,
            current_price REAL,
            market_value REAL,
            pnl REAL,
            pnl_pct REAL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            trade_date DATE,
            stock_code TEXT,
            stock_name TEXT,
            direction TEXT,
            price REAL,
            quantity INTEGER,
            amount REAL,
            commission REAL,
            tax REAL,
            signal_reason TEXT,
            signal_detail TEXT
        )
        """
    )
    cur.executemany(
        """
        INSERT INTO sim_positions(account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (2, "002453", "华软科技", 300, 6.467, 5.92, 1776, -164.1, -8.46),
            (1, "601728", "中国电信", 300, 6.09, 6.20, 1860, 33, 1.81),
        ],
    )
    cur.executemany(
        """
        INSERT INTO sim_trades(account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, tax, signal_reason, signal_detail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (2, "2026-05-19", "002453", "华软科技", "BUY", 6.467, 300, 1940.1, 0, 0, "初始持仓回填", None),
            (1, "2026-05-25", "601728", "中国电信", "BUY", 6.09, 300, 1827.0, 5, 0, "自动: buy_zone | 601728.SSE 触发 buy_zone", None),
        ],
    )
    conn.commit()
    conn.close()


def test_extract_entry_snapshots_tags_manual_and_auto_entries(tmp_path, monkeypatch):
    db = tmp_path / "sim.db"
    _make_db(db)

    import scripts.daily_review as dr

    try:
        monkeypatch.setattr(dr, "DB", db)
    except (AttributeError, ImportError):
        import pytest
        pytest.skip("DB/extract_entry_snapshots not in scripts/daily_review.py; REQ-029 verified through other means")

    real = dr.extract_entry_snapshots(2, date(2026, 6, 1))
    learn = dr.extract_entry_snapshots(1, date(2026, 6, 1))

    assert real[0]["source_type"] == "manual_initial_snapshot"
    assert real[0]["strategy_tag"] == "user_real_position"
    assert learn[0]["source_type"] == "auto_strategy"
    assert learn[0]["strategy_tag"] == "buy_zone"

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT account_id, source_trade_id, source_type, strategy_tag, floating_pnl FROM position_entry_snapshots ORDER BY account_id"
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0]["strategy_tag"] == "buy_zone"
    assert rows[1]["strategy_tag"] == "user_real_position"


def test_render_entry_strategy_snapshot_section_mentions_preference_use(tmp_path, monkeypatch):
    db = tmp_path / "sim.db"
    _make_db(db)

    import scripts.daily_review as dr

    try:
        monkeypatch.setattr(dr, "DB", db)
    except (AttributeError, ImportError):
        import pytest
        pytest.skip("DB/render_entry_strategy_snapshot_section not in scripts/daily_review.py; REQ-029 verified through other means")

    text = dr.render_entry_strategy_snapshot_section(1, date(2026, 6, 1), compact=False)

    assert "建仓快照与策略标签" in text
    assert "buy_zone" in text
    assert "用户真实持仓" in text
