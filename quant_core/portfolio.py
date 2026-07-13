"""
quant_core/portfolio.py — 组合构建模块

QL-009: 全股票共享现金、持仓和风险额度。
替代"每只股票独立资金再平均"的不可投资 leaderboard。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as Date
from typing import Optional

from .domain import PositionSnapshot, SignalIntent, Direction
from .fees import FeeModel, FeeBreakdown


@dataclass
class PortfolioConfig:
    """组合配置"""
    max_position_pct: float = 0.2          # 单股最大仓位比例
    max_total_positions: int = 6           # 最大持仓数
    max_daily_new: int = 3                 # 每日最大新建仓
    max_industry_pct: float = 0.3          # 行业集中度上限
    risk_budget_per_trade: float = 0.02    # 单笔风险预算
    cash_reserve_pct: float = 0.05         # 现金预留


@dataclass
class PortfolioState:
    """组合状态 — 实时追踪"""
    cash: float = 0.0
    total_value: float = 0.0
    positions: dict[str, PositionSnapshot] = field(default_factory=dict)
    daily_pnl: float = 0.0
    cumulative_return: float = 0.0
    max_drawdown: float = 0.0
    peak_value: float = 0.0

    # 日频追踪
    daily_new_count: int = 0
    daily_trade_count: int = 0
    trade_date: Optional[str] = None

    @property
    def market_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def position_count(self) -> int:
        return len(self.positions)

    def check_integrity(self, tolerance: float = 0.01) -> bool:
        """验证: 现金 + 持仓市值 = 总资产"""
        return abs(self.cash + self.market_value - self.total_value) < tolerance

    def update_drawdown(self):
        """更新最大回撤"""
        if self.total_value > self.peak_value:
            self.peak_value = self.total_value
        if self.peak_value > 0:
            dd = (self.peak_value - self.total_value) / self.peak_value
            self.max_drawdown = max(self.max_drawdown, dd)


def calculate_position_size(
    signal: SignalIntent,
    portfolio_state: PortfolioState,
    config: PortfolioConfig,
    stop_loss_pct: float = -0.08,
) -> int:
    """风险预算仓位计算 — 替代固定100股/固定金额

    EXP-004: 按波动率和止损距离分配风险
    position_value = min(
        portfolio_value * max_position_pct,
        risk_budget_per_trade / abs(expected_loss_pct)
    )
    """
    if signal.direction != Direction.LONG:
        return 0

    # 单股仓位上限
    max_position_value = portfolio_state.total_value * config.max_position_pct

    # 风险预算
    if stop_loss_pct != 0:
        risk_based_value = portfolio_state.total_value * config.risk_budget_per_trade / abs(stop_loss_pct)
    else:
        risk_based_value = max_position_value

    target_value = min(max_position_value, risk_based_value)

    # 现金检查
    available_cash = portfolio_state.cash * (1 - config.cash_reserve_pct)
    target_value = min(target_value, available_cash)

    # 简化: 用信号目标价计算股数
    if signal.target_price and signal.target_price > 0:
        shares = int(target_value / signal.target_price)
        shares = (shares // 100) * 100  # A股100股单位
        return max(shares, 0)

    return 0
