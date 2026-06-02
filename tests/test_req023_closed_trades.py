"""REQ-023: 已平仓历史交易 FIFO 盈亏分析。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
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
            broker TEXT,
            signal_reason TEXT
        )"""
    )
    rows = [
        # A: two buy lots then one partial sell, validates FIFO avg cost and fees.
        (1, "2026-05-27", "600001", "测试A", "BUY", 10.0, 100, 1000.0, 1.0, 0.0, "sim", "buy1"),
        (1, "2026-05-28", "600001", "测试A", "BUY", 11.0, 100, 1100.0, 1.0, 0.0, "sim", "buy2"),
        (1, "2026-05-29", "600001", "测试A", "SELL", 12.0, 150, 1800.0, 1.5, 1.5, "sim", "sell"),
        # B: losing round trip.
        (1, "2026-05-28", "600002", "测试B", "BUY", 10.0, 100, 1000.0, 0.0, 0.0, "qmt", "buy"),
        (1, "2026-06-01", "600002", "测试B", "SELL", 9.0, 100, 900.0, 0.0, 0.0, "qmt", "sell"),
    ]
    conn.executemany(
        """INSERT INTO sim_trades
           (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, tax, broker, signal_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()


def _conn(path: Path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def test_analyze_closed_trades_fifo_metrics(tmp_path):
    from sim.closed_trades import analyze_closed_trades

    db = tmp_path / "closed.db"
    _seed_db(db)

    data = analyze_closed_trades(1, date(2026, 6, 1), conn_factory=lambda: _conn(db))
    summary = data["summary"]

    assert summary["closed_count"] == 2
    assert summary["win_count"] == 1
    assert summary["loss_count"] == 1
    assert summary["win_rate"] == 50.0
    assert summary["net_pnl"] == pytest.approx(145.5)  # A +245.5, B -100
    assert summary["profit_factor"] == pytest.approx(2.455)
    assert summary["payoff_ratio"] == pytest.approx(2.455)
    assert summary["max_profit_trade"]["stock_code"] == "600001"
    assert summary["max_loss_trade"]["stock_code"] == "600002"

    a = next(r for r in data["closed_trades"] if r["stock_code"] == "600001")
    assert a["quantity"] == 150
    assert a["avg_cost"] == pytest.approx((100 * 10 + 50 * 11) / 150)
    assert a["pnl"] == pytest.approx(245.5)
    assert a["holding_days"] == 2


def test_daily_review_renders_closed_trade_section(tmp_path, monkeypatch):
    import scripts.daily_review as dr

    db = tmp_path / "closed.db"
    _seed_db(db)

    def fake_conn():
        return _conn(db)

    monkeypatch.setattr(dr, "get_conn", fake_conn)
    md = dr.render_closed_trades_analysis_section(1, date(2026, 6, 1))

    assert "已平仓历史交易分析" in md
    assert "胜率：**50.00%**" in md
    assert "单笔最大盈利" in md
    assert "个股" in md

    compact = dr.render_closed_trades_analysis_section(1, date(2026, 6, 1), compact=True)
    assert "平仓复盘" in compact
    assert "个股贡献" in compact
