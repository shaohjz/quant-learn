"""费率试算仓位：低价股不能被最低佣金 5 元系统性误杀。

2026-08-29 实测：光大银行 3.03 元，100 股 = 303 元触发最低佣金 5 元，
算出的费率 3.35%；按 8000 元预算（2600 股）实际费率 0.18%，失真 18.9 倍。
净盈亏比被这个费率吃掉后必然为负，低价股结构性选不出来。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import swing_auto as sa  # noqa: E402


def test_default_is_legacy_100_shares():
    """不传 fee_budget 时必须是 100 股——账户 #3 行为零变化的前提。"""
    assert sa.fee_test_shares(3.03, None) == 100
    assert sa.fee_test_shares(39.35, None) == 100


def test_budget_rounds_down_to_lot_of_100():
    assert sa.fee_test_shares(3.03, 8000.0) == 2600
    assert sa.fee_test_shares(39.35, 8000.0) == 200
    assert sa.fee_test_shares(3.03, 10.0) == 100  # 不足 1 手时兜底 100 股


def test_low_price_fee_ratio_collapses_with_budget():
    """低价股按预算试算后，费率必须显著下降。"""
    price, resist = 3.03, 3.06
    shares = sa.fee_test_shares(price, 8000.0)

    legacy = sa.calc_fees(price, resist, 100) / (price * 100)
    budgeted = sa.calc_fees(price, resist, shares) / (price * shares)

    assert legacy > 0.03          # 旧算法：>3%
    assert budgeted < 0.005       # 新算法：<0.5%
    assert legacy / budgeted > 10  # 失真一个数量级以上


def test_high_price_stock_barely_changes():
    """高价股不该被这个改动影响——避免误伤 #3 的大票。"""
    price = 39.35
    shares = sa.fee_test_shares(price, 10000.0)

    legacy = sa.calc_fees(price, price * 1.01, 100) / (price * 100)
    budgeted = sa.calc_fees(price, price * 1.01, shares) / (price * shares)

    assert abs(legacy - budgeted) < 0.005


def test_run_scan_logs_instead_of_swallowing(monkeypatch, caplog):
    """扫描单只股票抛异常时必须留下日志，不能静默 pass。

    原实现是 `except Exception: pass`，扫描整池失败时不会留下任何痕迹，
    产物表现为「今日无信号」，与「真的没有信号」无法区分。
    """
    import logging

    import swing_daily_report as sdr

    monkeypatch.setattr(sdr, "get_stock_pool", lambda: [("sh600000", "浦发银行")])
    monkeypatch.setattr(sdr, "save_results", lambda *_a, **_k: None)
    monkeypatch.setattr(sdr.time, "sleep", lambda *_a: None)

    def boom(*_a, **_k):
        raise RuntimeError("行情接口炸了")

    monkeypatch.setattr(sdr, "scan_stock", boom)

    with caplog.at_level(logging.WARNING):
        out = sdr.run_scan()

    assert out == []
    assert "浦发银行" in caplog.text
