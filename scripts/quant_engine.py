"""
quant_engine.py — 新入口，直接使用 quant_core 全套接口

设计目标:
  - 提供 QuantEngine 类，封装 quant_core 的 FeeModel / ThresholdStrategyCore /
    ExecutionPolicy / RiskEngine / PortfolioState / PerformanceMetrics
  - 与旧 sim_executor.py 并行存在，不替代旧功能
  - 纯内存计算 + 可选 DB 持久化
"""

from __future__ import annotations

import logging
import sys
from datetime import date as Date, datetime
from pathlib import Path
from typing import Any, Optional

# ── 项目根路径 ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── quant_core 全套接口 ──────────────────────────────────────────
from quant_core.domain import (
    Bar, Direction, Fill, FillSource, OrderIntent, OrderSide,
    OrderType, PriceSource, SignalIntent,
)
from quant_core.fees import FeeConfig, FeeModel
from quant_core.execution import ExecutionConfig, ExecutionPolicy
from quant_core.strategy import PortfolioState, StrategyCore, ThresholdStrategyCore
from quant_core.metrics import (
    PerformanceMetrics,
    calc_sharpe, calc_sortino, calc_max_drawdown,
    calc_net_expectancy, calc_excess_return, calc_information_ratio,
)
from quant_core.portfolio import PortfolioConfig, calculate_position_size
from quant_core.risk import RiskCheckResult, RiskEngine, TradingHealthGate

logger = logging.getLogger(__name__)


class QuantEngine:
    """量化引擎 — 直接使用 quant_core 全套接口。

    用法:
        engine = QuantEngine()
        engine.set_strategy(ThresholdStrategyCore())
        signal = engine.run_strategy(features, portfolio_state, config, as_of)
        fill = engine.execute_order(order_intent, next_bar)
        metrics = engine.calc_performance(nav_series)
    """

    def __init__(
        self,
        fee_model: Optional[FeeModel] = None,
        execution_policy: Optional[ExecutionPolicy] = None,
        risk_engine: Optional[RiskEngine] = None,
        portfolio_config: Optional[PortfolioConfig] = None,
    ):
        self._fee_model = fee_model or FeeModel()
        self._execution_policy = execution_policy or ExecutionPolicy(
            fee_model=self._fee_model,
        )
        self._risk_engine = risk_engine or RiskEngine(
            config=portfolio_config or PortfolioConfig(),
        )
        self._portfolio_config = portfolio_config or PortfolioConfig()
        self._strategy: Optional[StrategyCore] = None
        self._trading_health_gate = TradingHealthGate()

    # ── 策略管理 ──────────────────────────────────────────────────

    def set_strategy(self, strategy: StrategyCore) -> None:
        """设置策略核心。"""
        self._strategy = strategy

    def run_strategy(
        self,
        features: dict[str, Any],
        portfolio_state: PortfolioState,
        strategy_config: dict,
        as_of: Date,
    ) -> list[SignalIntent]:
        """运行策略，生成信号意图。"""
        if self._strategy is None:
            raise RuntimeError("Strategy not set. Call set_strategy() first.")
        return self._strategy.decide(features, portfolio_state, strategy_config, as_of)

    # ── 风控 ──────────────────────────────────────────────────────

    def check_signal(
        self,
        signal: SignalIntent,
        portfolio_state: PortfolioState,
    ) -> RiskCheckResult:
        """信号前风控检查。"""
        return self._risk_engine.check_signal(signal, portfolio_state)

    def check_trading_health(self) -> bool:
        """交易健康门控 — fail closed。"""
        return self._trading_health_gate.can_open_new_position()

    def update_health_status(self, **kwargs) -> None:
        """更新健康门控状态。"""
        self._trading_health_gate.update_status(**kwargs)

    # ── 执行 ──────────────────────────────────────────────────────

    def create_order_intent(
        self,
        signal: SignalIntent,
        quantity: int,
        order_type: OrderType = OrderType.MARKET,
    ) -> OrderIntent:
        """从 SignalIntent 创建 OrderIntent。"""
        side = OrderSide.BUY if signal.direction == Direction.LONG else OrderSide.SELL
        price = signal.target_price or 0.0
        return OrderIntent(
            symbol=signal.symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            signal_intent=signal,
            signal_time=datetime.now(),
        )

    def execute_order(
        self,
        intent: OrderIntent,
        next_bar: Optional[Bar] = None,
        portfolio_holdings: Optional[dict[str, int]] = None,
        signal_date: Optional[Date] = None,
        trade_date: Optional[Date] = None,
    ) -> Optional[Fill]:
        """执行订单，返回成交记录（或 None 表示无法成交）。"""
        return self._execution_policy.execute(
            intent=intent,
            next_bar=next_bar,
            portfolio_holdings=portfolio_holdings,
            signal_date=signal_date,
            trade_date=trade_date,
        )

    # ── 仓位计算 ─────────────────────────────────────────────────

    def calc_position_size(
        self,
        signal: SignalIntent,
        portfolio_state: PortfolioState,
        stop_loss_pct: float = -0.08,
    ) -> int:
        """风险预算仓位计算。"""
        return calculate_position_size(
            signal=signal,
            portfolio_state=portfolio_state,
            config=self._portfolio_config,
            stop_loss_pct=stop_loss_pct,
        )

    # ── 费用计算 ──────────────────────────────────────────────────

    def calc_fees(
        self,
        side: str,
        amount: float,
        trade_date: Optional[Date] = None,
        exchange: str = "SH",
    ) -> dict:
        """计算交易费用。"""
        fees = self._fee_model.calculate(
            side=side,
            amount=amount,
            trade_date=trade_date,
            exchange=exchange,
        )
        return {
            "commission": fees.commission,
            "stamp_tax": fees.stamp_tax,
            "transfer_fee": fees.transfer_fee,
            "total": fees.total,
        }

    # ── 指标计算 ──────────────────────────────────────────────────

    def calc_performance(
        self,
        nav_series: list[float],
        returns: Optional[list[float]] = None,
        risk_free_rate: float = 0.02,
    ) -> PerformanceMetrics:
        """计算绩效指标。"""
        if returns is None:
            returns = []
            for i in range(1, len(nav_series)):
                if nav_series[i - 1] > 0:
                    returns.append((nav_series[i] - nav_series[i - 1]) / nav_series[i - 1])

        total_return = (nav_series[-1] - nav_series[0]) / nav_series[0] if nav_series else 0.0
        cagr = (nav_series[-1] / nav_series[0]) ** (1.0 / max(len(nav_series) / 252, 0.1)) - 1 if len(nav_series) > 1 and nav_series[0] > 0 else 0.0
        max_dd = calc_max_drawdown(nav_series)
        sharpe = calc_sharpe(returns, risk_free_rate)
        sortino = calc_sortino(returns, risk_free_rate)

        return PerformanceMetrics(
            total_return=total_return,
            cagr=cagr,
            annual_volatility=0.0,  # 需外部传入
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=cagr / max_dd if max_dd > 0 else 0.0,
            max_drawdown=max_dd,
            total_trades=0,
        )

    # ── 时序验证 ──────────────────────────────────────────────────

    @staticmethod
    def validate_timing(signal_date: Date, fill_date: Date) -> bool:
        """验证 T+1 执行时序。"""
        from quant_core.execution import validate_execution_timing
        return validate_execution_timing(signal_date, fill_date)

    # ── 工具方法 ──────────────────────────────────────────────────

    @staticmethod
    def create_bar(
        symbol: str,
        exchange: str,
        open_p: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        amount: float = 0.0,
        timestamp: Optional[datetime] = None,
    ) -> Bar:
        """快速创建 Bar 对象。"""
        return Bar(
            symbol=symbol,
            exchange=exchange,
            timestamp=timestamp or datetime.now(),
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=volume,
            amount=amount,
        )

    @staticmethod
    def create_portfolio_state(
        cash: float = 0.0,
        total_value: float = 0.0,
        positions: Optional[dict] = None,
        max_positions: int = 6,
        max_daily_new: int = 3,
    ) -> PortfolioState:
        """快速创建组合状态。"""
        from quant_core.strategy import PortfolioState as _PS
        return _PS(
            cash=cash,
            total_value=total_value,
            positions=positions or {},
            max_positions=max_positions,
            max_daily_new=max_daily_new,
        )


# ── CLI 入口 ──────────────────────────────────────────────────────
def main():
    """简单验证入口。"""
    engine = QuantEngine()
    engine.set_strategy(ThresholdStrategyCore())
    print(f"QuantEngine initialized. Strategy: {engine._strategy.name}")
    print("All quant_core modules loaded successfully.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
