"""Half take-profit (+1R) and ATR-hybrid trailing stop."""
from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_calc_trailing_stop_atr_hybrid_raises_floor():
    from scripts.sim_executor import calc_trailing_stop
    import scripts.sim_executor as se

    # Ladder alone at +12%: lock +2% = 10.2
    assert calc_trailing_stop(10.0, 11.2, None, atr_pct=None)[0] == 10.2

    # With tight ATR (2%), atr floor = 11.2 * (1 - 2*0.02) = 10.752 > 10.2
    stop, reason = calc_trailing_stop(10.0, 11.2, None, atr_pct=2.0)
    assert se.TRAILING_MODE in ('atr', 'atr_hybrid')
    assert stop == pytest.approx(10.75, abs=0.01)
    assert "ATR" in reason


def test_scale_out_target_and_gate(monkeypatch):
    import scripts.sim_executor as se

    monkeypatch.setattr(se, "STOP_LOSS_PCT", -0.08)
    monkeypatch.setattr(se, "SCALE_OUT_AT_R", 1.0)
    monkeypatch.setattr(se, "SCALE_OUT_ENABLED", True)
    monkeypatch.setattr(se, "TAKE_PROFIT_MODE", "half")
    monkeypatch.setattr(se, "SCALE_OUT_MIN_QTY", 200)

    assert se._scale_out_target_price(10.0) == pytest.approx(10.8)

    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INT, stock_code TEXT, direction TEXT, trade_date TEXT
        )"""
    )
    conn.execute(
        "INSERT INTO sim_trades (account_id, stock_code, direction, trade_date) "
        "VALUES (1,'600001','BUY','2026-07-01')"
    )

    ok, reason = se._check_cost_scale_out(conn, "600001", 10.79, 200, 10.0, 1)
    assert ok is False

    ok, reason = se._check_cost_scale_out(conn, "600001", 10.80, 200, 10.0, 1)
    assert ok is True
    assert "半仓止盈" in reason

    # Already sold once since buy → no second scale-out
    conn.execute(
        "INSERT INTO sim_trades (account_id, stock_code, direction, trade_date) "
        "VALUES (1,'600001','SELL','2026-07-02')"
    )
    ok, _ = se._check_cost_scale_out(conn, "600001", 11.0, 200, 10.0, 1)
    assert ok is False


def test_take_profit_decide_half_then_full(monkeypatch, tmp_path):
    import scripts.sim_executor as se

    db = tmp_path / "tp.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE sim_positions (account_id INT, stock_code TEXT, quantity INT, avg_cost REAL)"
    )
    conn.execute(
        "CREATE TABLE sim_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INT, "
        "stock_code TEXT, direction TEXT, trade_date TEXT)"
    )
    conn.execute("INSERT INTO sim_positions VALUES (1,'600001',200,10.0)")
    conn.execute(
        "INSERT INTO sim_trades (account_id, stock_code, direction, trade_date) "
        "VALUES (1,'600001','BUY','2026-07-01')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(se, "_DB_PATH", str(db))
    monkeypatch.setattr(se, "_ACCOUNT_ID", 1)
    monkeypatch.setattr(se, "TAKE_PROFIT_MODE", "half")
    monkeypatch.setattr(se, "_write_review_decision", lambda *a, **k: None)

    action = se.decide_action(
        {"code": "600001", "name": "测", "level": "take_profit", "trigger": 12.0, "dir": "above"},
        12.0,
    )
    assert action == "SELL_HALF"

    # Mark scaled, then second take_profit clears runner
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO sim_trades (account_id, stock_code, direction, trade_date) "
        "VALUES (1,'600001','SELL','2026-07-02')"
    )
    conn.execute("UPDATE sim_positions SET quantity=100 WHERE stock_code='600001'")
    conn.commit()
    conn.close()

    action = se.decide_action(
        {"code": "600001", "name": "测", "level": "take_profit", "trigger": 12.0, "dir": "above"},
        12.5,
    )
    assert action == "SELL_ALL"
