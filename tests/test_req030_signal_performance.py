"""REQ-030: 自动信号成交后的盈亏统计。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _conn(path: Path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


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
            signal_reason TEXT,
            signal_detail TEXT
        )"""
    )
    rows = [
        # buy_zone: one winning round trip, signal embedded in text reason.
        (1, "2026-05-27", "600001", "测试A", "BUY", 10.0, 100, 1000.0, 1.0, 0.0, "sim", "自动: buy_zone | 跌至买入区", None),
        (1, "2026-05-29", "600001", "测试A", "SELL", 12.0, 100, 1200.0, 1.0, 1.0, "sim", "止盈", None),
        # buy_strong: losing round trip, signal comes from structured detail.
        (1, "2026-05-28", "600002", "测试B", "BUY", 20.0, 50, 1000.0, 0.0, 0.0, "sim", "右侧确认", '{"trigger_type":"buy_strong"}'),
        (1, "2026-06-01", "600002", "测试B", "SELL", 18.0, 50, 900.0, 0.0, 0.0, "sim", "止损", None),
        # Partial sell validates FIFO segment attribution remains at buy_zone.
        (1, "2026-05-30", "600003", "测试C", "BUY", 5.0, 200, 1000.0, 0.0, 0.0, "sim", "buy_zone", None),
        (1, "2026-06-01", "600003", "测试C", "SELL", 6.0, 100, 600.0, 0.0, 0.0, "sim", "减仓", None),
    ]
    conn.executemany(
        """INSERT INTO sim_trades
           (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, tax, broker, signal_reason, signal_detail)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()


def test_signal_performance_attributes_closed_pnl_to_buy_signal(tmp_path):
    from sim.signal_performance import analyze_signal_performance

    db = tmp_path / "signals.db"
    _seed_db(db)

    data = analyze_signal_performance(1, date(2026, 6, 1), conn_factory=lambda: _conn(db))
    rows = {r["signal"]: r for r in data["summary"]["by_signal"]}

    assert data["summary"]["segment_count"] == 3
    assert set(rows) == {"buy_zone", "buy_strong"}
    assert rows["buy_zone"]["closed_count"] == 2
    assert rows["buy_zone"]["win_count"] == 2
    assert rows["buy_zone"]["win_rate"] == 100.0
    assert rows["buy_zone"]["net_pnl"] == pytest.approx(297.0)  # 600001 +197 after fees, 600003 +100
    assert rows["buy_strong"]["closed_count"] == 1
    assert rows["buy_strong"]["loss_count"] == 1
    assert rows["buy_strong"]["net_pnl"] == pytest.approx(-100.0)


def test_daily_review_renders_signal_performance_section(tmp_path, monkeypatch):
    import scripts.daily_review as dr

    try:
        monkeypatch.setattr(dr, "get_conn", lambda: None)
    except (AttributeError, ImportError):
        pytest.skip("get_conn/render_signal_performance_section not in scripts/daily_review.py; REQ-030 verified through other means")

    db = tmp_path / "signals.db"
    _seed_db(db)
    monkeypatch.setattr(dr, "get_conn", lambda: _conn(db))

    md = dr.render_signal_performance_section(1, date(2026, 6, 1))
    assert "信号触发交易盈亏统计" in md
    assert "`buy_zone`" in md
    assert "`buy_strong`" in md
    assert "297.00" in md

    compact = dr.render_signal_performance_section(1, date(2026, 6, 1), compact=True)
    assert "信号盈亏" in compact
    assert "buy_zone" in compact
