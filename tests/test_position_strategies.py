"""中长线低买高卖纯函数测试。"""

from dataclasses import replace
from datetime import date

from quant_core.horizon import HorizonParams
from quant_core.position_strategies import (
    PositionFeatures,
    WARMUP_BARS,
    evaluate_position_buy,
    evaluate_position_sell,
    extract_features_from_arrays,
)


def _feat(**changes) -> PositionFeatures:
    base = PositionFeatures(
        close=10.0,
        ma20=10.2,
        ma60=10.5,
        ma120=11.0,
        low60=9.6,
        rsi14=35.0,
        weekday=4,
    )
    return replace(base, **changes)


def test_extract_features_needs_120_bars():
    assert extract_features_from_arrays(close=[10.0] * (WARMUP_BARS - 1)) is None
    feat = extract_features_from_arrays(close=[10.0] * WARMUP_BARS, weekday=4)
    assert feat is not None
    assert feat.ma60 == 10.0
    assert feat.low60 == 10.0


def test_mean_revert_buys_near_60day_low():
    params = HorizonParams(enabled=True, style="mean_revert", rsi_buy=40, near_low60_pct=0.05)
    result = evaluate_position_buy(_feat(close=9.90, low60=9.60, rsi14=32, ma60=10.5), params)
    assert result.allowed is True
    assert result.reason_code == "MEAN_REVERT"


def test_mean_revert_blocks_not_cheap_and_high_rsi():
    params = HorizonParams(enabled=True, style="mean_revert", rsi_buy=40)
    far = evaluate_position_buy(_feat(close=12.0, low60=9.0, ma60=10.0, rsi14=30), params)
    assert far.reason_code == "NOT_CHEAP"
    hot = evaluate_position_buy(_feat(close=9.70, low60=9.60, ma60=12.0, ma120=10.0, rsi14=55), params)
    assert hot.reason_code == "RSI_NOT_OVERSOLD"


def test_mean_revert_blocks_below_ma120_floor():
    params = HorizonParams(enabled=True, ma120_floor=0.90)
    result = evaluate_position_buy(_feat(close=8.0, ma120=12.0, low60=7.9, rsi14=20), params)
    assert result.reason_code == "BELOW_MA120_FLOOR"


def test_weekly_only_skips_tuesday():
    params = HorizonParams(enabled=True, weekly_only=True)
    tue = evaluate_position_buy(_feat(weekday=1), params)
    assert tue.reason_code == "WEEKLY_ONLY"
    fri = evaluate_position_buy(_feat(weekday=4, close=9.70, low60=9.60, ma120=10.0), params)
    assert fri.allowed is True


def test_trend_pullback_requires_ma20_and_ma60():
    params = HorizonParams(
        enabled=True,
        style="trend_pullback",
        rsi_buy=50,
        ma20_pullback_band=0.02,
    )
    ok = evaluate_position_buy(_feat(close=10.1, ma20=10.0, ma60=9.8, rsi14=45), params)
    assert ok.allowed is True
    assert ok.reason_code == "TREND_PULLBACK"
    broken = evaluate_position_buy(_feat(close=9.0, ma60=10.0, ma20=9.0), params)
    assert broken.reason_code == "TREND_BROKEN"


def test_sell_disaster_bypasses_min_hold():
    params = HorizonParams(enabled=True, stop_loss_pct=0.12, min_hold_days=20)
    result = evaluate_position_sell(
        features=_feat(close=8.5),
        params=params,
        avg_cost=10.0,
        held_days=2,
    )
    assert result.allowed is True
    assert result.reason_code == "DISASTER_STOP"


def test_sell_respects_min_hold_before_take_profit():
    params = HorizonParams(enabled=True, take_profit_pct=0.20, min_hold_days=10)
    held = evaluate_position_sell(
        features=_feat(close=12.5),
        params=params,
        avg_cost=10.0,
        held_days=3,
    )
    assert held.reason_code == "MIN_HOLD"
    ready = evaluate_position_sell(
        features=_feat(close=12.5),
        params=params,
        avg_cost=10.0,
        held_days=10,
    )
    assert ready.reason_code == "TAKE_PROFIT"


def test_mean_revert_sells_when_back_to_ma60():
    params = HorizonParams(
        enabled=True,
        style="mean_revert",
        take_profit_pct=0.50,
        min_hold_days=5,
        sell_on_ma60_recover=True,
        sell_ma60_band=0.02,
    )
    result = evaluate_position_sell(
        features=_feat(close=10.8, ma60=10.5),
        params=params,
        avg_cost=10.0,
        held_days=8,
    )
    assert result.reason_code == "MA60_RECOVER"
