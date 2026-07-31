from datetime import date as Date

import pandas as pd
import pytest

from quant_core.domain import OrderSide
from quant_core.metrics import PerformanceMetrics
from research.portfolio_backtest import (
    BacktestConfig,
    TradeRequest,
    run_portfolio_backtest,
)


def _bars(opens, closes=None, start="2024-01-02", exchange="SH"):
    closes = closes or opens
    dates = pd.bdate_range(start, periods=len(opens))
    return pd.DataFrame(
        {
            "open": opens,
            "high": [max(o, c) + 1 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 1 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": [1_000_000] * len(opens),
            "exchange": [exchange] * len(opens),
            "adjustment_type": ["raw"] * len(opens),
        },
        index=dates,
    )


def test_signal_never_fills_on_same_bar_and_uses_next_raw_open():
    bars = {"600001": _bars([10.0, 20.0, 21.0])}

    def strategy(context):
        if context.date == Date(2024, 1, 2):
            return [TradeRequest("600001", OrderSide.BUY, 100)]
        return []

    result = run_portfolio_backtest(
        bars,
        strategy,
        BacktestConfig(initial_cash=100_000, max_position_pct=1.0),
    )

    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade["signal_date"] == Date(2024, 1, 2)
    assert trade["trade_date"] == Date(2024, 1, 3)
    assert trade["price"] == 20.0
    assert trade["price_source"] == "next_open"
    assert result.audit["same_bar_allowed"] is False
    assert result.audit["adjustment_type"] == "raw"


def test_symbols_share_one_cash_pool():
    bars = {
        "600001": _bars([10.0, 10.0, 10.0]),
        "600002": _bars([10.0, 10.0, 10.0]),
    }

    def strategy(context):
        if context.date == Date(2024, 1, 2):
            return [
                TradeRequest("600001", "BUY", 1_000),
                TradeRequest("600002", "BUY", 1_000),
            ]
        return []

    result = run_portfolio_backtest(
        bars,
        strategy,
        BacktestConfig(
            initial_cash=15_000,
            max_positions=2,
            max_position_pct=1.0,
            max_daily_new_positions=2,
        ),
    )

    quantities = dict(zip(result.trades["symbol"], result.trades["quantity"]))
    assert quantities == {"600001": 1_000, "600002": 400}
    assert result.trades.iloc[-1]["cash_after"] >= 0
    assert result.trades["amount"].sum() == 14_000


def test_unified_fees_are_doubled_and_deducted_from_cash():
    bars = {"600001": _bars([10.0, 10.0])}

    def strategy(context):
        if context.date == Date(2024, 1, 2):
            return [{"symbol": "600001", "side": "BUY", "quantity": 100}]
        return []

    result = run_portfolio_backtest(
        bars,
        strategy,
        BacktestConfig(initial_cash=10_000, max_position_pct=1.0, cost_multiplier=2.0),
    )

    trade = result.trades.iloc[0]
    # FeeModel: 最低佣金 5 元 + 沪市过户费 0.01 元，再乘 2。
    assert trade["commission"] == 10.0
    assert trade["transfer_fee"] == 0.02
    assert trade["stamp_tax"] == 0.0
    assert trade["total_fees"] == 10.02
    assert trade["cash_after"] == pytest.approx(10_000 - 1_000 - 10.02)
    assert result.metrics.total_fees == pytest.approx(10.02)


def test_portfolio_integrity_after_buys_and_sell():
    bars = {"600001": _bars([10.0, 11.0, 12.0, 13.0])}

    def strategy(context):
        if context.date == Date(2024, 1, 2):
            return [TradeRequest("600001", "BUY", 100)]
        if context.date == Date(2024, 1, 3):
            return [TradeRequest("600001", "SELL", 100)]
        return []

    result = run_portfolio_backtest(
        bars,
        strategy,
        BacktestConfig(initial_cash=10_000, max_position_pct=1.0),
    )

    assert list(result.trades["side"]) == ["BUY", "SELL"]
    assert (result.nav["integrity_error"].abs() < 1e-9).all()
    assert (result.nav["cash"] + result.nav["market_value"]).equals(result.nav["total_value"])
    assert result.nav.iloc[-1]["positions"] == 0
    assert isinstance(result.metrics, PerformanceMetrics)
    assert result.metrics.total_trades == 2
    assert len(result.data_hash) == 64
    assert len(result.config_hash) == 64


def test_adjusted_execution_prices_are_rejected():
    bars = _bars([10.0, 11.0])
    bars["adjustment_type"] = "forward"

    with pytest.raises(ValueError, match="unadjusted/raw"):
        run_portfolio_backtest({"600001": bars}, lambda context: [])
