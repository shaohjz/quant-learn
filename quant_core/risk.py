"""
quant_core/risk.py — 组合与订单前风控

QL-012: 统一风险引擎 — 数据或关键风控不可用时 fail closed。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .domain import SignalIntent, Direction, OrderSide
from .portfolio import PortfolioState, PortfolioConfig


@dataclass
class RiskCheckResult:
    """风控检查结果"""
    allowed: bool
    reason: str = ""
    details: dict = field(default_factory=dict)


class RiskEngine:
    """组合与订单前风控"""

    def __init__(self, config: Optional[PortfolioConfig] = None):
        self._config = config or PortfolioConfig()

    def check_signal(
        self,
        signal: SignalIntent,
        portfolio_state: PortfolioState,
    ) -> RiskCheckResult:
        """信号前风控检查"""
        reasons: list[str] = []

        # 1. 仓位上限
        if signal.direction == Direction.LONG:
            if portfolio_state.position_count >= self._config.max_total_positions:
                reasons.append(f"已达最大持仓数 {self._config.max_total_positions}")

            # 日频新建限制
            if portfolio_state.daily_new_count >= self._config.max_daily_new:
                reasons.append(f"已达每日新建仓上限 {self._config.max_daily_new}")

            # 单股仓位
            symbol = signal.symbol
            if symbol in portfolio_state.positions:
                pos = portfolio_state.positions[symbol]
                pos_pct = pos.market_value / portfolio_state.total_value if portfolio_state.total_value > 0 else 0
                if pos_pct >= self._config.max_position_pct:
                    reasons.append(f"单股仓位 {pos_pct:.1%} 超限 {self._config.max_position_pct:.1%}")

        # 2. 现金检查
        if signal.direction == Direction.LONG:
            cash_reserve = portfolio_state.cash * self._config.cash_reserve_pct
            available = portfolio_state.cash - cash_reserve
            if available <= 0:
                reasons.append("可用资金不足（扣除预留后）")

        if reasons:
            return RiskCheckResult(
                allowed=False,
                reason="; ".join(reasons),
                details={"reasons": reasons},
            )

        return RiskCheckResult(allowed=True, reason="all checks passed")


class TradingHealthGate:
    """QL-012: 交易健康门控 — fail closed

    对新开仓 fail closed；平仓按独立降级策略处理。
    告警发送失败不阻断风控，但必须进入本地 durable queue。
    """

    def __init__(self):
        self._market_data_ok: bool = False
        self._calendar_ok: bool = False
        self._oms_reconciled: bool = False
        self._db_writable: bool = False
        self._risk_snapshot_ok: bool = False

    def can_open_new_position(self) -> bool:
        """是否允许新开仓 — fail closed: 任何一项不OK则拒绝"""
        return all([
            self._market_data_ok,
            self._calendar_ok,
            self._oms_reconciled,
            self._db_writable,
            self._risk_snapshot_ok,
        ])

    def can_close_position(self) -> bool:
        """是否允许平仓 — 降级: 只需要 DB 可写"""
        return self._db_writable

    def update_status(
        self,
        market_data_ok: Optional[bool] = None,
        calendar_ok: Optional[bool] = None,
        oms_reconciled: Optional[bool] = None,
        db_writable: Optional[bool] = None,
        risk_snapshot_ok: Optional[bool] = None,
    ):
        """更新健康状态"""
        if market_data_ok is not None:
            self._market_data_ok = market_data_ok
        if calendar_ok is not None:
            self._calendar_ok = calendar_ok
        if oms_reconciled is not None:
            self._oms_reconciled = oms_reconciled
        if db_writable is not None:
            self._db_writable = db_writable
        if risk_snapshot_ok is not None:
            self._risk_snapshot_ok = risk_snapshot_ok

    def get_status(self) -> dict:
        """获取当前健康状态"""
        return {
            "market_data": self._market_data_ok,
            "calendar": self._calendar_ok,
            "oms_reconciled": self._oms_reconciled,
            "db_writable": self._db_writable,
            "risk_snapshot": self._risk_snapshot_ok,
            "can_open": self.can_open_new_position(),
            "can_close": self.can_close_position(),
        }
