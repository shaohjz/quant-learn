"""账户 #1 与账户 #3 的无 IO 买入决策。

本模块只接收已经准备好的行情、账户快照和参数，不读取文件、数据库或网络。
生产适配层可将 :class:`BuySignalResult` 转为统一的 ``SignalIntent``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import isclose, isfinite

from .domain import Direction, SignalIntent


@dataclass(frozen=True)
class ExistingPosition:
    """与买入闸门相关的最小持仓快照；``pnl_pct`` 使用百分数。"""

    quantity: int = 0
    pnl_pct: float = 0.0
    trailing_stop_price: float = 0.0


@dataclass(frozen=True)
class Account1BuyInput:
    """账户 #1 buy_zone 决策的完整纯数据输入。"""

    symbol: str
    date: date
    close: float
    buy_zone: float
    ma10: float
    ma20: float
    volume_ratio: float
    market_change_pct: float
    expected_rr: float
    position: ExistingPosition = field(default_factory=ExistingPosition)


@dataclass(frozen=True)
class Account1BuyParams:
    """账户 #1 参数，默认值与 2026-09-08 收紧后的赚钱闸基线一致。"""

    weak_market_enabled: bool = True
    weak_market_change_pct: float = -1.0
    block_add_to_loser_pct: float = 0.0
    min_expected_rr: float = 0.0
    max_below_ma10_pct: float | None = 0.03
    require_ma10_above_ma20: bool = True
    forbid_add_below_stop: bool = True
    confidence: float = 0.60


@dataclass(frozen=True)
class SwingBuyInput:
    """账户 #3 A/B 波段信号输入。"""

    symbol: str
    date: date
    close: float
    ma10: float
    ma20: float
    volume_ratio: float
    expected_rr: float
    auxiliary_score: int = 0


@dataclass(frozen=True)
class SwingBuyParams:
    """账户 #3 参数，默认值复刻 ``swing_auto`` 的 A/B 基线。"""

    a_ma20_tolerance: float = 0.015
    b_ma10_tolerance: float = 0.01
    max_volume_ratio: float = 0.8
    a_score: int = 4
    b_score: int = 3
    min_score: int = 5
    min_expected_rr: float = 1.2
    confidence: float = 0.65


@dataclass(frozen=True)
class BuySignalResult:
    """结构化决策结果；禁买结果的 ``to_signal_intent`` 返回 ``None``。"""

    symbol: str
    date: date
    account_id: int
    strategy: str
    allowed: bool
    reason_code: str
    reason: str
    close: float
    expected_rr: float
    score: int = 0
    setup: str | None = None
    matched_setups: tuple[str, ...] = ()
    confidence: float = 0.0

    def to_signal_intent(self) -> SignalIntent | None:
        """将可买结果转换为统一信号；禁买不是交易意图。"""

        if not self.allowed:
            return None
        return SignalIntent(
            symbol=self.symbol,
            direction=Direction.LONG,
            confidence=self.confidence,
            reason=self.reason,
            target_price=self.close,
            as_of=self.date,
        )


def _require_finite(name: str, value: float, *, positive: bool = False) -> None:
    if not isfinite(value) or (positive and value <= 0):
        qualifier = "正数" if positive else "有限数"
        raise ValueError(f"{name} 必须是{qualifier}")


def _within_relative_band(value: float, reference: float, tolerance: float) -> bool:
    deviation = abs(value - reference) / reference
    return deviation <= tolerance or isclose(
        deviation,
        tolerance,
        rel_tol=1e-12,
        abs_tol=1e-12,
    )


def _blocked(
    *,
    symbol: str,
    as_of: date,
    account_id: int,
    strategy: str,
    code: str,
    reason: str,
    close: float,
    expected_rr: float,
    score: int = 0,
    setup: str | None = None,
    matched_setups: tuple[str, ...] = (),
) -> BuySignalResult:
    return BuySignalResult(
        symbol=symbol,
        date=as_of,
        account_id=account_id,
        strategy=strategy,
        allowed=False,
        reason_code=code,
        reason=reason,
        close=close,
        expected_rr=expected_rr,
        score=score,
        setup=setup,
        matched_setups=matched_setups,
    )


def evaluate_account1_buy_zone(
    data: Account1BuyInput,
    params: Account1BuyParams | None = None,
) -> BuySignalResult:
    """评估账户 #1 buy_zone。

    买点必须同时不高于配置的 ``buy_zone`` 和当日 MA10。默认还要求
    MA10≥MA20（趋势未坏）、现价低于 MA10 不超过 3%、浮亏不加仓、
    买价不得落在跟踪止损下方。量比保留在输入快照中用于审计。
    """

    params = params or Account1BuyParams()
    if not data.symbol:
        raise ValueError("symbol 不能为空")
    for name in ("close", "buy_zone", "ma10", "ma20"):
        _require_finite(name, getattr(data, name), positive=True)
    for name in ("volume_ratio", "market_change_pct", "expected_rr"):
        _require_finite(name, getattr(data, name))
    _require_finite("position.pnl_pct", data.position.pnl_pct)
    _require_finite("position.trailing_stop_price", data.position.trailing_stop_price)
    if data.position.quantity < 0:
        raise ValueError("position.quantity 不能为负数")
    if data.position.trailing_stop_price < 0:
        raise ValueError("position.trailing_stop_price 不能为负数")
    if params.max_below_ma10_pct is not None and params.max_below_ma10_pct < 0:
        raise ValueError("max_below_ma10_pct 不能为负数")

    strategy = "account1_buy_zone"
    if data.close > data.buy_zone or data.close > data.ma10:
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=1,
            strategy=strategy,
            code="ABOVE_BUY_ZONE",
            reason=(f"收盘价 {data.close:.2f} 未同时进入 buy_zone {data.buy_zone:.2f}/MA10 {data.ma10:.2f}"),
            close=data.close,
            expected_rr=data.expected_rr,
        )

    if params.require_ma10_above_ma20 and data.ma10 < data.ma20:
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=1,
            strategy=strategy,
            code="TREND_NOT_CONFIRMED",
            reason=f"趋势未确认：MA10 {data.ma10:.2f} < MA20 {data.ma20:.2f}",
            close=data.close,
            expected_rr=data.expected_rr,
        )

    below_ma10_pct = (data.ma10 - data.close) / data.ma10
    if params.max_below_ma10_pct is not None and below_ma10_pct > params.max_below_ma10_pct:
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=1,
            strategy=strategy,
            code="TOO_FAR_BELOW_MA10",
            reason=(f"价格低于 MA10 {below_ma10_pct:.2%}，超过允许值 {params.max_below_ma10_pct:.2%}"),
            close=data.close,
            expected_rr=data.expected_rr,
        )

    if params.weak_market_enabled and data.market_change_pct <= params.weak_market_change_pct:
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=1,
            strategy=strategy,
            code="WEAK_MARKET",
            reason=(f"弱市禁买：市场涨跌 {data.market_change_pct:.2f}% <= {params.weak_market_change_pct:.2f}%"),
            close=data.close,
            expected_rr=data.expected_rr,
        )

    if data.position.quantity > 0 and data.position.pnl_pct <= params.block_add_to_loser_pct:
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=1,
            strategy=strategy,
            code="ADD_TO_LOSER",
            reason=(f"浮亏不加仓：持仓浮亏 {data.position.pnl_pct:.2f}% <= {params.block_add_to_loser_pct:.2f}%"),
            close=data.close,
            expected_rr=data.expected_rr,
        )

    if (
        data.position.quantity > 0
        and params.forbid_add_below_stop
        and data.position.trailing_stop_price > 0
        and data.close <= data.position.trailing_stop_price
    ):
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=1,
            strategy=strategy,
            code="ADD_BELOW_STOP",
            reason=(
                f"加仓价 {data.close:.2f} <= 跟踪止损 "
                f"{data.position.trailing_stop_price:.2f}，禁止止损线下加仓"
            ),
            close=data.close,
            expected_rr=data.expected_rr,
        )

    if data.expected_rr < params.min_expected_rr:
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=1,
            strategy=strategy,
            code="RR_TOO_LOW",
            reason=(f"预期盈亏比 {data.expected_rr:.2f} < 门槛 {params.min_expected_rr:.2f}"),
            close=data.close,
            expected_rr=data.expected_rr,
        )

    reason = (
        f"buy_zone：收盘价 {data.close:.2f} <= "
        f"buy_zone {data.buy_zone:.2f}/MA10 {data.ma10:.2f}，"
        f"预期盈亏比 {data.expected_rr:.2f}"
    )
    return BuySignalResult(
        symbol=data.symbol,
        date=data.date,
        account_id=1,
        strategy=strategy,
        allowed=True,
        reason_code="BUY_ZONE",
        reason=reason,
        close=data.close,
        expected_rr=data.expected_rr,
        setup="buy_zone",
        matched_setups=("buy_zone",),
        confidence=params.confidence,
    )


def evaluate_account3_swing(
    data: SwingBuyInput,
    params: SwingBuyParams | None = None,
) -> BuySignalResult:
    """评估账户 #3 波段 A/B；区间边界包含，量比上限不包含。"""

    params = params or SwingBuyParams()
    if not data.symbol:
        raise ValueError("symbol 不能为空")
    for name in ("close", "ma10", "ma20"):
        _require_finite(name, getattr(data, name), positive=True)
    for name in ("volume_ratio", "expected_rr"):
        _require_finite(name, getattr(data, name))
    if data.auxiliary_score < 0:
        raise ValueError("auxiliary_score 不能为负数")
    if params.a_ma20_tolerance < 0 or params.b_ma10_tolerance < 0:
        raise ValueError("均线容差不能为负数")

    a_match = _within_relative_band(
        data.close,
        data.ma20,
        params.a_ma20_tolerance,
    )
    b_match = _within_relative_band(
        data.close,
        data.ma10,
        params.b_ma10_tolerance,
    )
    volume_ok = data.volume_ratio < params.max_volume_ratio
    matched = tuple(setup for setup, matches in (("A", a_match), ("B", b_match)) if matches and volume_ok)
    score = (params.a_score if "A" in matched else 0) + (params.b_score if "B" in matched else 0) + data.auxiliary_score
    setup = matched[0] if matched else None
    strategy = "account3_swing_ab"

    if (a_match or b_match) and not volume_ok:
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=3,
            strategy=strategy,
            code="VOLUME_TOO_HIGH",
            reason=(f"量比 {data.volume_ratio:.2f} >= 上限 {params.max_volume_ratio:.2f}"),
            close=data.close,
            expected_rr=data.expected_rr,
        )
    if not matched:
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=3,
            strategy=strategy,
            code="NO_AB_SETUP",
            reason="收盘价未进入 MA20±A容差 或 MA10±B容差",
            close=data.close,
            expected_rr=data.expected_rr,
        )
    if score < params.min_score:
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=3,
            strategy=strategy,
            code="SCORE_TOO_LOW",
            reason=f"波段评分 {score} < 门槛 {params.min_score}",
            close=data.close,
            expected_rr=data.expected_rr,
            score=score,
            setup=setup,
            matched_setups=matched,
        )
    if data.expected_rr < params.min_expected_rr:
        return _blocked(
            symbol=data.symbol,
            as_of=data.date,
            account_id=3,
            strategy=strategy,
            code="RR_TOO_LOW",
            reason=(f"预期盈亏比 {data.expected_rr:.2f} < 门槛 {params.min_expected_rr:.2f}"),
            close=data.close,
            expected_rr=data.expected_rr,
            score=score,
            setup=setup,
            matched_setups=matched,
        )

    reason = (
        f"波段{'/'.join(matched)}：缩量回踩，量比 {data.volume_ratio:.2f}，"
        f"评分 {score}，预期盈亏比 {data.expected_rr:.2f}"
    )
    return BuySignalResult(
        symbol=data.symbol,
        date=data.date,
        account_id=3,
        strategy=strategy,
        allowed=True,
        reason_code="SWING_AB",
        reason=reason,
        close=data.close,
        expected_rr=data.expected_rr,
        score=score,
        setup=setup,
        matched_setups=matched,
        confidence=params.confidence,
    )
