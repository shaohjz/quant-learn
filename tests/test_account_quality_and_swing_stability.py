"""#1 质量闸 / #3 固定止损 / 最低佣金 / 同日换仓冷却。"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def test_commission_for_small_buy_uses_min_five_yuan():
    from scripts.sim_executor import commission_for_amount

    # 国电南瑞那笔 9010 × 万2.5 = 2.25，旧路径会入账 2.25
    assert commission_for_amount(9010.25, side="BUY") == 5.0
    assert commission_for_amount(20000.0, side="BUY") == 5.0  # 20000*0.00025=5.0
    assert commission_for_amount(40000.0, side="BUY") == 10.0


def test_swing_accounts_do_not_use_atr_trailing():
    from scripts.sim_executor import uses_atr_trailing

    assert uses_atr_trailing(1) is True
    assert uses_atr_trailing(2) is True
    assert uses_atr_trailing(3) is False
    assert uses_atr_trailing(4) is False


def test_apply_buy_zone_quality_gates():
    from scripts.sim_executor import apply_buy_zone_quality_gates

    ok, _ = apply_buy_zone_quality_gates(
        10.0, 10.0, 9.8, max_below_ma10_pct=0.03, require_ma10_above_ma20=True
    )
    assert ok is True
    knife, reason = apply_buy_zone_quality_gates(
        9.5, 10.0, 9.8, max_below_ma10_pct=0.03, require_ma10_above_ma20=True
    )
    assert knife is False
    assert "飞刀" in reason
    trend, reason2 = apply_buy_zone_quality_gates(
        9.7, 9.8, 10.0, max_below_ma10_pct=0.03, require_ma10_above_ma20=True
    )
    assert trend is False
    assert "趋势" in reason2


def test_sync_swing_fixed_stops_resets_raised_trailing(tmp_path, monkeypatch):
    import scripts.swing_daily_report as sdr

    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE sim_positions ("
        "id INTEGER PRIMARY KEY, account_id INTEGER, stock_code TEXT, "
        "quantity INTEGER, avg_cost REAL, trailing_stop_price REAL)"
    )
    conn.execute(
        "INSERT INTO sim_positions (account_id, stock_code, quantity, avg_cost, trailing_stop_price) "
        "VALUES (3, '600309', 100, 74.73, 75.48)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(sdr, "DB_PATH", db)
    monkeypatch.setattr(sdr, "SWING_ACCOUNT_ID", 3)
    monkeypatch.setattr(sdr, "STOP_LOSS_PCT", 0.05)

    n = sdr.sync_swing_fixed_stops(3)
    assert n == 1
    conn = sqlite3.connect(db)
    stop = conn.execute("SELECT trailing_stop_price FROM sim_positions").fetchone()[0]
    conn.close()
    assert stop == round(74.73 * 0.95, 2)


def test_execute_sim_skips_buy_after_same_day_sell(monkeypatch):
    import scripts.swing_daily_report as sdr

    monkeypatch.setattr(sdr, "allow_same_day_replace", lambda: False)
    monkeypatch.setattr(sdr, "today_sold_codes", lambda _today: {"002714"})
    monkeypatch.setattr(
        sdr,
        "sim_sell",
        lambda p, price, reason: {"ok": True, "side": "SELL", "code": "002714"},
    )
    bought = []

    def _buy(*_a, **_k):
        bought.append(1)
        return {"ok": True, "side": "BUY"}

    monkeypatch.setattr(sdr, "sim_buy", _buy)
    fills = sdr.execute_sim(
        [{"action": "SELL_TP", "current_price": 43.4, "action_reason": "盘中止盈"}],
        [{"code": "300059", "name": "东方财富", "price": 19.35, "signal_type": "A",
          "score": 7, "net_rr": 1.42}],
    )
    assert any(f.get("side") == "SELL" for f in fills)
    assert bought == []
