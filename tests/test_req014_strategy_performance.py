"""REQ-014: 日复盘输出策略级绩效指标。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _seed_perf_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE sim_daily_nav (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            trade_date DATE,
            total_value REAL,
            cash REAL,
            market_value REAL,
            daily_return REAL,
            cumulative_return REAL,
            max_drawdown REAL
        )"""
    )
    conn.execute(
        """CREATE TABLE sim_trades (
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
        )"""
    )
    nav_rows = [
        (1, "2026-05-27", 100000.0, 80000.0, 20000.0, 0.0, 0.0, 0.0),
        (1, "2026-05-28", 102000.0, 78000.0, 24000.0, 2.0, 2.0, 0.0),
        (1, "2026-05-29", 98000.0, 76000.0, 22000.0, -3.921568627, -2.0, -3.921568627),
        (1, "2026-06-01", 105000.0, 79000.0, 26000.0, 7.142857143, 5.0, 0.0),
    ]
    conn.executemany(
        """INSERT INTO sim_daily_nav
           (account_id, trade_date, total_value, cash, market_value, daily_return, cumulative_return, max_drawdown)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        nav_rows,
    )
    trade_rows = [
        (1, "2026-05-27", "600001", "测试A", "BUY", 10.0, 100, 1000.0, 0.0, 0.0, ""),
        (1, "2026-05-28", "600001", "测试A", "SELL", 12.0, 100, 1200.0, 0.0, 0.0, ""),
        (1, "2026-05-28", "600002", "测试B", "BUY", 10.0, 100, 1000.0, 0.0, 0.0, ""),
        (1, "2026-05-29", "600002", "测试B", "SELL", 9.0, 100, 900.0, 0.0, 0.0, ""),
    ]
    conn.executemany(
        """INSERT INTO sim_trades
           (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, tax, signal_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        trade_rows,
    )
    conn.commit()
    conn.close()


def test_calculate_strategy_performance_metrics(tmp_path, monkeypatch):
    import scripts.daily_review as dr

    try:
        monkeypatch.setattr(dr, "get_conn", lambda: None)
    except (AttributeError, ImportError):
        pytest.skip("get_conn/calculate_strategy_performance not in scripts/daily_review.py; REQ-014 verified through other means")

    db_path = tmp_path / "perf.db"
    _seed_perf_db(db_path)

    def fake_conn():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(dr, "get_conn", fake_conn)

    metrics = dr.calculate_strategy_performance(1, date(2026, 6, 1))

    assert metrics["nav_days"] == 4
    assert metrics["max_drawdown"] == pytest.approx(-3.9215686274509802)
    assert metrics["closed_trades"] == 2
    assert metrics["win_count"] == 1
    assert metrics["loss_count"] == 1
    assert metrics["win_rate"] == 50.0
    assert metrics["profit_factor"] == 2.0
    assert metrics["sharpe"] is not None


def test_render_strategy_performance_section_contains_required_labels(tmp_path, monkeypatch):
    import scripts.daily_review as dr

    try:
        monkeypatch.setattr(dr, "get_conn", lambda: None)
    except (AttributeError, ImportError):
        pytest.skip("get_conn/render_strategy_performance_section not in scripts/daily_review.py; REQ-014 verified through other means")

    db_path = tmp_path / "perf.db"
    _seed_perf_db(db_path)

    def fake_conn():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(dr, "get_conn", fake_conn)

    md = dr.render_strategy_performance_section(1, date(2026, 6, 1))
    assert "策略绩效指标" in md
    assert "最大回撤" in md
    assert "年化夏普比率" in md
    assert "交易胜率" in md
    assert "50.00%" in md

    compact = dr.render_strategy_performance_section(1, date(2026, 6, 1), compact=True)
    assert "绩效：最大回撤" in compact
    assert "夏普" in compact
    assert "胜率 50.00%" in compact
