"""Trade expectancy hygiene: exclude snapshot fills; gate buy_strong / hard stop."""
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


def _seed_mixed(path: Path) -> None:
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
        # Snapshot contamination — must not drag strategy win rate.
        (1, "2026-05-19", "600330", "天通股份", "BUY", 32.0, 100, 3200.0, 0.0, 0.0,
         "live_mirror_init", "初始化建仓快照（用户真实持仓）"),
        (1, "2026-06-02", "600330", "天通股份", "SELL", 28.0, 100, 2800.0, 1.0, 1.0,
         "sim", "stop_loss"),
        # Real strategy round trip — winner.
        (1, "2026-05-21", "001896", "豫能控股", "BUY", 14.0, 100, 1400.0, 1.0, 0.0,
         "sim", "自动: buy_zone | 试探建仓"),
        (1, "2026-06-10", "001896", "豫能控股", "SELL", 18.0, 100, 1800.0, 1.0, 1.0,
         "sim", "take_profit"),
    ]
    conn.executemany(
        """INSERT INTO sim_trades
           (account_id, trade_date, stock_code, stock_name, direction, price, quantity,
            amount, commission, tax, broker, signal_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    conn.close()


def test_closed_trades_strategy_only_excludes_snapshot(tmp_path):
    from sim.closed_trades import analyze_closed_trades

    db = tmp_path / "mix.db"
    _seed_mixed(db)
    data = analyze_closed_trades(1, date(2026, 6, 10), conn_factory=lambda: _conn(db))

    assert data["excluded_non_strategy_count"] == 1
    assert data["summary"]["closed_count"] == 1
    assert data["summary"]["win_rate"] == 100.0
    assert data["summary_all"]["closed_count"] == 2
    assert data["summary_all"]["win_rate"] == 50.0
    assert data["closed_trades"][0]["entry_signal"] == "buy_zone"
    assert data["closed_trades"][0]["is_strategy"] is True


def test_signal_performance_collapses_snapshot_label(tmp_path):
    from sim.signal_performance import analyze_signal_performance

    db = tmp_path / "mix.db"
    _seed_mixed(db)
    data = analyze_signal_performance(1, date(2026, 6, 10), conn_factory=lambda: _conn(db))

    assert data["excluded_non_strategy_count"] == 1
    labels = {r["signal"] for r in data["summary"]["by_signal"]}
    assert labels == {"buy_zone"}
    all_labels = {r["signal"] for r in data["summary_all"]["by_signal"]}
    assert "init_snapshot" in all_labels


def test_same_day_hard_stop_bypass_and_buy_strong_gate(monkeypatch):
    import scripts.sim_executor as se

    monkeypatch.setattr(se, "HARD_STOP_BYPASSES_SAME_DAY", True)
    monkeypatch.setattr(se, "STOP_LOSS_PCT", -0.08)
    monkeypatch.setattr(se, "BUY_STRONG_ENABLED", False)
    monkeypatch.setattr(se, "POST_BUY_PROTECT_LOSS_PCT", -8.0)
    monkeypatch.setattr(se, "_write_review_decision", lambda *a, **k: None)

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE sim_positions (account_id INT, stock_code TEXT, avg_cost REAL, quantity INT)"
    )
    conn.execute(
        "INSERT INTO sim_positions VALUES (1, '600001', 10.0, 100)"
    )

    # Soft trend_break at -3% must NOT bypass.
    allowed, _ = se._same_day_hard_stop_allowed(conn, "600001", 9.7, "trend_break", 1)
    assert allowed is False

    # Cost already -8% may bypass.
    allowed, reason = se._same_day_hard_stop_allowed(conn, "600001", 9.2, "trend_break", 1)
    assert allowed is True
    assert ("硬止损" in reason) or ("浮亏" in reason)

    # hard_stop level always bypasses when flag on.
    allowed, _ = se._same_day_hard_stop_allowed(conn, "600001", 9.9, "hard_stop", 1)
    assert allowed is True

    # buy_strong disabled → NO_ACTION (gate runs before DB cash checks)
    action = se.decide_action(
        {"code": "600001", "name": "测试", "level": "buy_strong", "trigger": 9.0, "dir": "below"},
        8.5,
    )
    assert action == "NO_ACTION"
