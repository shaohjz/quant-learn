"""赚钱闸：单票仓位上限必须裁剪预算（此前 config 有字段但未执行）。"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path


def _make_db(total_value: float = 100_000.0, cash: float = 50_000.0) -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sim_account ("
        "id INTEGER PRIMARY KEY, cash REAL, total_value REAL)"
    )
    conn.execute(
        "CREATE TABLE sim_positions ("
        "account_id INTEGER, stock_code TEXT, quantity INTEGER, "
        "avg_cost REAL, current_price REAL, market_value REAL, pnl_pct REAL)"
    )
    conn.execute(
        "INSERT INTO sim_account (id, cash, total_value) VALUES (1, ?, ?)",
        (cash, total_value),
    )
    # 已有京东方仓位约 14.8% → 剩余空间不够一手 → 预算裁到不够买
    conn.execute(
        "INSERT INTO sim_positions "
        "(account_id, stock_code, quantity, avg_cost, current_price, market_value, pnl_pct) "
        "VALUES (1, '000725', 3700, 4.0, 4.0, 14800, -2.0)"
    )
    conn.commit()
    conn.close()
    return path


def test_cap_budget_blocks_when_position_full(monkeypatch):
    db = _make_db()
    monkeypatch.setenv("QUANT_DB_PATH", db)
    # 重新加载模块常量会麻烦；直接测函数并注入 MAX_POSITION_PCT
    import scripts.sim_executor as se

    monkeypatch.setattr(se, "MAX_POSITION_PCT", 0.15)
    monkeypatch.setattr(se, "_DB_PATH", db)

    conn = sqlite3.connect(db)
    try:
        budget, reason = se._cap_budget_by_position_pct(
            conn, 1, "000725", cur_price=4.0, budget=10000.0
        )
    finally:
        conn.close()
        Path(db).unlink(missing_ok=True)

    # 已有 14800，上限 15000，剩余空间 200 < 一手 400 → 预算变 0
    assert budget < 4.0 * 100, reason
    assert "仓位" in reason


def test_cap_budget_allows_new_name(monkeypatch):
    db = _make_db()
    monkeypatch.setenv("QUANT_DB_PATH", db)
    import scripts.sim_executor as se

    monkeypatch.setattr(se, "MAX_POSITION_PCT", 0.15)
    monkeypatch.setattr(se, "_DB_PATH", db)

    conn = sqlite3.connect(db)
    try:
        budget, reason = se._cap_budget_by_position_pct(
            conn, 1, "600519", cur_price=100.0, budget=10000.0
        )
    finally:
        conn.close()
        Path(db).unlink(missing_ok=True)

    assert budget == 10000.0
    assert "裁剪" in reason or "上限" in reason


def test_market_panic_blocks_at_minus_one():
    from vqlearn.services.buy_risk_guard import evaluate_market_panic

    d = evaluate_market_panic(index_changes_pct={"沪深300": -1.2})
    assert d.blocked is True
    assert "熔断" in d.reason
