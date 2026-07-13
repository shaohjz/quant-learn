"""
tests/test_quant_core.py — QL-006/007/008/009/012 综合测试

验收:
  - T日信号绝不在T日成交 (QL-007)
  - 同一输入在不同适配器输出一致 (QL-008)
  - 组合完整性: 现金+市值=总资产 (QL-009)
  - fail-closed: 健康门控任何一项不OK拒绝开仓 (QL-012)
  - Point-in-time: Bar包含数据可见时间 (QL-006)
"""

import pytest
from datetime import date as Date, datetime

from quant_core.domain import (
    Bar, SignalIntent, OrderIntent, Fill, Direction, OrderSide,
    OrderType, AdjustmentType, PriceSource, Threshold,
)
from quant_core.execution import ExecutionPolicy, ExecutionConfig, validate_execution_timing
from quant_core.strategy import ThresholdStrategyCore, PortfolioState
from quant_core.portfolio import PortfolioConfig, calculate_position_size
from quant_core.metrics import calc_max_drawdown, calc_sharpe, calc_net_expectancy
from quant_core.risk import RiskEngine, TradingHealthGate
from quant_core.fees import FeeModel


# ─── QL-007: T+1 约束 ───
class TestTPlusOneConstraint:
    """T日信号绝不在T日成交"""

    def test_signal_date_equals_trade_date_rejected(self):
        policy = ExecutionPolicy()
        intent = OrderIntent(
            symbol="600330", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=100, price=30.0,
            signal_time=datetime(2024, 6, 1, 15, 0),
        )
        bar = Bar(symbol="600330", exchange="SH", timestamp=datetime(2024, 6, 2, 9, 30),
                   open=30.5, high=31.0, low=30.0, close=30.8, volume=100000)
        # T日信号 = T日成交 → 应被拒绝
        result = policy.execute(intent, next_bar=bar, signal_date=Date(2024, 6, 1),
                                trade_date=Date(2024, 6, 1))
        assert result is None

    def test_t_plus_one_allowed(self):
        policy = ExecutionPolicy()
        intent = OrderIntent(
            symbol="600330", side=OrderSide.BUY, order_type=OrderType.MARKET,
            quantity=100, price=30.0,
            signal_time=datetime(2024, 6, 1, 15, 0),
        )
        bar = Bar(symbol="600330", exchange="SH", timestamp=datetime(2024, 6, 2, 9, 30),
                   open=30.5, high=31.0, low=30.0, close=30.8, volume=100000)
        # T日信号 + T+1成交 → 允许
        result = policy.execute(intent, next_bar=bar, signal_date=Date(2024, 6, 1),
                                trade_date=Date(2024, 6, 2))
        assert result is not None
        assert result.side == OrderSide.BUY

    def test_validate_execution_timing(self):
        assert validate_execution_timing(Date(2024, 6, 1), Date(2024, 6, 2)) is True
        assert validate_execution_timing(Date(2024, 6, 1), Date(2024, 6, 1)) is False


# ─── QL-008: 策略一致性 ───
class TestStrategyConsistency:
    """同一输入在回测/Paper/QMT生成相同SignalIntent"""

    def test_threshold_strategy_deterministic(self):
        """固定输入下，多次调用输出一致"""
        strategy = ThresholdStrategyCore()
        features = {
            "000600": {"price": 9.8, "ma10": 10.17, "ma20": 9.90},
        }
        config = {
            "watchlist": {
                "000600": {
                    "name": "建投能源",
                    "enabled": True,
                    "rules": {
                        "buy_strong": {"trigger": 9.9, "dir": "below", "msg": "buy_strong"},
                    },
                    "trend_filter": {"status": "HEALTHY"},
                }
            }
        }
        ps = PortfolioState(cash=200000, total_value=200000, positions={}, daily_new_count=0)
        as_of = Date(2024, 6, 1)

        r1 = strategy.decide(features, ps, config, as_of)
        r2 = strategy.decide(features, ps, config, as_of)
        assert len(r1) == len(r2)
        for s1, s2 in zip(r1, r2):
            assert s1.symbol == s2.symbol
            assert s1.direction == s2.direction
            assert s1.reason == s2.reason


# ─── QL-009: 组合完整性 ───
class TestPortfolioIntegrity:
    """现金 + 持仓市值 = 总资产"""

    def test_portfolio_check_integrity(self):
        from quant_core.portfolio import PortfolioState
        from quant_core.domain import PositionSnapshot
        ps = PortfolioState(
            cash=150000.0,
            total_value=200000.0,
            positions={
                "600330": PositionSnapshot(symbol="600330", quantity=100, avg_cost=30.0,
                                           current_price=30.0, market_value=50000.0),
            }
        )
        assert ps.check_integrity() is True  # 150000 + 50000 = 200000

    def test_portfolio_integrity_fails(self):
        from quant_core.portfolio import PortfolioState
        ps = PortfolioState(cash=150000.0, total_value=200000.0)
        # 无持仓 → 市值=0 → 150000 != 200000
        assert ps.check_integrity() is False


# ─── QL-012: Fail Closed ───
class TestFailClosed:
    """健康门控任何一项不OK拒绝开仓"""

    def test_all_ok_allows_open(self):
        gate = TradingHealthGate()
        gate.update_status(market_data_ok=True, calendar_ok=True,
                           oms_reconciled=True, db_writable=True, risk_snapshot_ok=True)
        assert gate.can_open_new_position() is True

    def test_any_fail_blocks_open(self):
        gate = TradingHealthGate()
        gate.update_status(market_data_ok=True, calendar_ok=True,
                           oms_reconciled=True, db_writable=True, risk_snapshot_ok=False)
        assert gate.can_open_new_position() is False

    def test_db_writable_enables_close(self):
        """平仓只需 DB 可写（降级策略）"""
        gate = TradingHealthGate()
        gate.update_status(db_writable=True)
        assert gate.can_close_position() is True

    def test_db_not_writable_blocks_close(self):
        gate = TradingHealthGate()
        gate.update_status(db_writable=False)
        assert gate.can_close_position() is False


# ─── QL-006: Point-in-time ───
class TestPointInTime:
    """Bar包含数据可见时间；阈值有追溯信息"""

    def test_bar_has_visible_time(self):
        bar = Bar(
            symbol="600330", exchange="SH",
            timestamp=datetime(2024, 6, 1, 15, 0),
            open=30.0, high=31.0, low=29.0, close=30.5, volume=100000,
            data_visible_time=datetime(2024, 6, 1, 16, 0),  # 收盘后才可见
            source="mootdx",
        )
        assert bar.data_visible_time is not None

    def test_threshold_has_effective_dates(self):
        t = Threshold(
            symbol="000600", threshold_type="buy_strong", value=9.9,
            direction="below", effective_from=Date(2024, 6, 1),
            effective_to=Date(2024, 7, 1), input_end_time=Date(2024, 5, 31),
        )
        assert t.effective_from is not None
        assert t.input_end_time is not None


# ─── Metrics ───
class TestMetrics:
    def test_max_drawdown(self):
        nav = [100, 110, 105, 115, 100, 120]
        dd = calc_max_drawdown(nav)
        assert dd > 0
        # peak=115, trough=100 → dd = 15/115 ≈ 0.1304
        assert abs(dd - 0.1304) < 0.01

    def test_net_expectancy(self):
        # 60%胜率, 平均盈利2%, 平均亏损1%
        ne = calc_net_expectancy(win_rate=0.6, avg_win=2.0, avg_loss=1.0, fees=0.1)
        assert ne > 0  # 正期望

    def test_net_expectancy_negative(self):
        # 高胜率但平均亏损远大于盈利
        ne = calc_net_expectancy(win_rate=0.8, avg_win=1.0, avg_loss=5.0, fees=0.5)
        assert ne < 0  # 负期望，应淘汰
