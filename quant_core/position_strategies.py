"""中长线低买高卖纯函数。无 IO。

买入看 60 日低点 / MA60（或趋势回踩 MA20），卖出看固定止盈止损、
回到均线或跌破 MA60。最短持有期内除灾难止损外不卖。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite

from .horizon import HorizonParams


WARMUP_BARS = 120


@dataclass(frozen=True)
class PositionFeatures:
    close: float
    ma20: float
    ma60: float
    ma120: float
    low60: float
    rsi14: float
    weekday: int  # 0=Mon … 6=Sun


@dataclass(frozen=True)
class PositionDecision:
    allowed: bool
    action: str  # BUY / SELL / HOLD
    reason_code: str
    reason: str


def _finite_positive(name: str, value: float) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} 必须是正数")


def extract_features_from_arrays(
    *,
    close: list[float] | tuple[float, ...],
    low: list[float] | tuple[float, ...] | None = None,
    weekday: int = 0,
) -> PositionFeatures | None:
    """从收盘价序列提取特征。长度不足 120 根则返回 None。"""

    n = len(close)
    if n < WARMUP_BARS:
        return None
    lows = list(low) if low is not None else list(close)
    if len(lows) != n:
        raise ValueError("low 与 close 长度必须一致")
    last = float(close[-1])
    ma20 = sum(close[-20:]) / 20
    ma60 = sum(close[-60:]) / 60
    ma120 = sum(close[-120:]) / 120
    low60 = min(float(x) for x in lows[-60:])
    rsi = _rsi14(close)
    return PositionFeatures(
        close=last,
        ma20=ma20,
        ma60=ma60,
        ma120=ma120,
        low60=low60,
        rsi14=rsi,
        weekday=int(weekday),
    )


def _rsi14(close: list[float] | tuple[float, ...], period: int = 14) -> float:
    if len(close) < period + 1:
        return 50.0
    gains = 0.0
    losses = 0.0
    window = close[-(period + 1) :]
    for i in range(1, len(window)):
        diff = float(window[i]) - float(window[i - 1])
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss <= 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def evaluate_position_buy(
    features: PositionFeatures,
    params: HorizonParams,
    *,
    as_of: date | None = None,
) -> PositionDecision:
    """评估是否开仓。``as_of`` 仅用于审计，不参与判定。"""

    del as_of
    _finite_positive("close", features.close)
    _finite_positive("ma20", features.ma20)
    _finite_positive("ma60", features.ma60)
    _finite_positive("low60", features.low60)
    if params.weekly_only and features.weekday < 4:
        return PositionDecision(False, "HOLD", "WEEKLY_ONLY", "只在本周最后一个交易日附近决策")

    style = params.style
    if style == "trend_pullback":
        return _buy_trend_pullback(features, params)
    return _buy_mean_revert(features, params)


def _buy_mean_revert(features: PositionFeatures, params: HorizonParams) -> PositionDecision:
    if params.ma120_floor is not None and features.ma120 > 0:
        floor = features.ma120 * params.ma120_floor
        if features.close < floor:
            return PositionDecision(
                False,
                "HOLD",
                "BELOW_MA120_FLOOR",
                f"现价 {features.close:.2f} < MA120×{params.ma120_floor:.2f}={floor:.2f}，不接飞刀",
            )
    near_low = features.close <= features.low60 * (1.0 + params.near_low60_pct)
    near_ma60 = abs(features.close - features.ma60) / features.ma60 <= params.ma60_buy_band
    if not (near_low or near_ma60):
        return PositionDecision(
            False,
            "HOLD",
            "NOT_CHEAP",
            (
                f"未靠近 60 日低点 {features.low60:.2f} 或 MA60 {features.ma60:.2f}"
            ),
        )
    if features.rsi14 > params.rsi_buy:
        return PositionDecision(
            False,
            "HOLD",
            "RSI_NOT_OVERSOLD",
            f"RSI14 {features.rsi14:.1f} > {params.rsi_buy:.0f}",
        )
    tag = "60日低点" if near_low else "MA60"
    return PositionDecision(
        True,
        "BUY",
        "MEAN_REVERT",
        f"低买：贴近{tag}，RSI14={features.rsi14:.0f}",
    )


def _buy_trend_pullback(features: PositionFeatures, params: HorizonParams) -> PositionDecision:
    if features.close < features.ma60 * 0.98:
        return PositionDecision(
            False,
            "HOLD",
            "TREND_BROKEN",
            f"现价 {features.close:.2f} 低于 MA60 {features.ma60:.2f}，不做回踩",
        )
    band = abs(features.close - features.ma20) / features.ma20
    if band > params.ma20_pullback_band:
        return PositionDecision(
            False,
            "HOLD",
            "NOT_AT_MA20",
            f"现价偏离 MA20 {band:.2%} > {params.ma20_pullback_band:.2%}",
        )
    if features.rsi14 > params.rsi_buy:
        return PositionDecision(
            False,
            "HOLD",
            "RSI_NOT_COOL",
            f"RSI14 {features.rsi14:.1f} > {params.rsi_buy:.0f}",
        )
    return PositionDecision(
        True,
        "BUY",
        "TREND_PULLBACK",
        f"趋势回踩 MA20，RSI14={features.rsi14:.0f}",
    )


def evaluate_position_sell(
    *,
    features: PositionFeatures,
    params: HorizonParams,
    avg_cost: float,
    held_days: int,
) -> PositionDecision:
    """评估是否平仓。灾难止损无视最短持有期。"""

    _finite_positive("close", features.close)
    _finite_positive("avg_cost", avg_cost)
    if held_days < 0:
        raise ValueError("held_days 不能为负")

    close = features.close
    stop_px = avg_cost * (1.0 - params.stop_loss_pct)
    take_px = avg_cost * (1.0 + params.take_profit_pct)
    if close <= stop_px:
        return PositionDecision(
            True,
            "SELL",
            "DISASTER_STOP",
            f"灾难止损 {close:.2f} ≤ {stop_px:.2f}（-{params.stop_loss_pct:.0%}）",
        )
    if held_days < params.min_hold_days:
        return PositionDecision(
            False,
            "HOLD",
            "MIN_HOLD",
            f"已持有 {held_days} 日 < 最短 {params.min_hold_days} 日",
        )
    if close >= take_px:
        return PositionDecision(
            True,
            "SELL",
            "TAKE_PROFIT",
            f"止盈 {close:.2f} ≥ {take_px:.2f}（+{params.take_profit_pct:.0%}）",
        )
    if params.style == "mean_revert" and params.sell_on_ma60_recover:
        recover = features.ma60 * (1.0 + params.sell_ma60_band)
        if close >= recover:
            return PositionDecision(
                True,
                "SELL",
                "MA60_RECOVER",
                f"回到均线 {close:.2f} ≥ MA60×{1 + params.sell_ma60_band:.2f}={recover:.2f}",
            )
    if params.style == "trend_pullback" and params.trend_break_ma60:
        if params.weekly_only and features.weekday < 4:
            return PositionDecision(False, "HOLD", "HOLD", "周线未收盘，不判破位")
        if close < features.ma60:
            return PositionDecision(
                True,
                "SELL",
                "MA60_BREAK",
                f"收盘 {close:.2f} 跌破 MA60 {features.ma60:.2f}",
            )
    return PositionDecision(False, "HOLD", "HOLD", "未到卖点")
