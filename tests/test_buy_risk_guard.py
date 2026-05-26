from datetime import datetime
from types import SimpleNamespace

from vqlearn.services.buy_risk_guard import (
    RiskDecision,
    evaluate_buy_risk_guard,
    evaluate_market_panic,
    evaluate_opening_crash_filter,
)


def test_market_panic_by_index_drop():
    d = evaluate_market_panic(index_changes_pct={"上证指数": -1.2})
    assert d.blocked is True
    assert "大盘情绪熔断" in d.reason
    assert d.details["trigger"] == "index"


def test_market_panic_by_breadth():
    d = evaluate_market_panic(declining_count=4100, total_count=5000)
    assert d.blocked is True
    assert d.details["trigger"] == "breadth"


def test_market_not_panic():
    d = evaluate_market_panic(index_changes_pct={"上证指数": -0.5}, declining_count=3000, total_count=5000)
    assert d.blocked is False


def test_opening_crash_filter_blocks_when_drop_volume_and_break_support():
    d = evaluate_opening_crash_filter(
        code="600000",
        current_price=9.2,
        open_price=9.4,
        prev_close=10.0,
        low_price=9.1,
        support_level=9.3,
        current_volume=2_000_000,
        avg_vol_5d=10_000_000,
        now=datetime(2026, 5, 26, 9, 40),
    )
    assert d.blocked is True
    assert "单票暴跌禁买" in d.reason


def test_opening_crash_filter_does_not_block_without_volume_spike():
    d = evaluate_opening_crash_filter(
        code="600000",
        current_price=9.2,
        open_price=9.4,
        prev_close=10.0,
        low_price=9.1,
        support_level=9.3,
        current_volume=100_000,
        avg_vol_5d=10_000_000,
        now=datetime(2026, 5, 26, 9, 40),
    )
    assert d.blocked is False
    assert "未放量" in d.reason


def test_buy_risk_guard_blocks_market_before_single_stock():
    tick = SimpleNamespace(last_price=9.2, open_price=9.4, pre_close=10.0, low_price=9.1, volume=2_000_000)

    def panic_fetcher():
        return RiskDecision(True, "大盘情绪熔断：测试", {"trigger": "index"})

    d = evaluate_buy_risk_guard(
        code="600000",
        tick=tick,
        prev_close=10.0,
        support_level=9.3,
        avg_vol_5d=10_000_000,
        market_fetcher=panic_fetcher,
    )
    assert d.blocked is True
    assert d.reason.startswith("大盘情绪熔断")
