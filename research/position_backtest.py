"""中长线组合回测：复用共享现金引擎，策略 callback 调 position_strategies。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date as Date
from typing import Any

import pandas as pd

from quant_core.domain import OrderSide
from quant_core.horizon import HorizonParams
from quant_core.position_strategies import (
    WARMUP_BARS,
    evaluate_position_buy,
    evaluate_position_sell,
    extract_features_from_arrays,
)
from research.portfolio_backtest import (
    BacktestConfig,
    StrategyCallback,
    StrategyContext,
    TradeRequest,
    run_portfolio_backtest,
)


def make_horizon_strategy(
    params: HorizonParams,
    *,
    trade_start: Date | None = None,
    trade_end: Date | None = None,
    buy_budget: float | None = None,
) -> StrategyCallback:
    budget = float(buy_budget if buy_budget is not None else params.single_budget)
    entry_dates: dict[str, Date] = {}

    def strategy(context: StrategyContext) -> list[TradeRequest]:
        if (trade_start and context.date < trade_start) or (trade_end and context.date > trade_end):
            return []
        for symbol in list(entry_dates):
            if symbol not in context.positions:
                entry_dates.pop(symbol, None)
        for symbol, pos in context.positions.items():
            if symbol not in entry_dates and pos.quantity > 0:
                entry_dates[symbol] = context.date

        requests: list[TradeRequest] = []
        for symbol in sorted(context.bars):
            frame = context.bars[symbol]
            features = _features(frame)
            if features is None:
                continue
            position = context.positions.get(symbol)
            if position is not None and position.quantity > 0:
                held = (context.date - entry_dates.get(symbol, context.date)).days
                decision = evaluate_position_sell(
                    features=features,
                    params=params,
                    avg_cost=position.avg_cost,
                    held_days=held,
                )
                if decision.allowed and decision.action == "SELL":
                    requests.append(
                        TradeRequest(symbol, OrderSide.SELL, position.quantity, decision.reason)
                    )
                continue
            decision = evaluate_position_buy(features, params, as_of=context.date)
            if decision.allowed:
                qty = int(budget / features.close / 100) * 100
                if qty > 0:
                    requests.append(TradeRequest(symbol, OrderSide.BUY, qty, decision.reason))
        return requests

    return strategy


def run_horizon_backtest(
    bars_by_symbol: Mapping[str, pd.DataFrame],
    params: HorizonParams,
    *,
    start: Date,
    end: Date,
    initial_cash: float,
    max_positions: int | None = None,
    buy_budget: float | None = None,
    max_daily_new_positions: int | None = None,
) -> dict[str, Any]:
    prepared = _prepare(bars_by_symbol, start, end)
    cfg = BacktestConfig(
        initial_cash=initial_cash,
        max_positions=int(max_positions if max_positions is not None else params.max_positions),
        max_position_pct=0.35,
        max_daily_new_positions=int(
            max_daily_new_positions
            if max_daily_new_positions is not None
            else params.max_daily_new_positions
        ),
    )
    callback = make_horizon_strategy(
        params,
        trade_start=start,
        trade_end=end,
        buy_budget=buy_budget if buy_budget is not None else params.single_budget,
    )
    result = run_portfolio_backtest(prepared, callback, cfg)
    sells = result.trades[result.trades["side"] == OrderSide.SELL.value] if not result.trades.empty else result.trades
    wins = int((sells["realized_pnl"] > 0).sum()) if not sells.empty else 0
    n_sells = int(len(sells))
    hold_days = _median_hold_days(result.trades)
    return {
        "params": params.as_dict(),
        "metrics": {
            "total_return": result.metrics.total_return,
            "max_drawdown": result.metrics.max_drawdown,
            "sharpe": result.metrics.sharpe_ratio,
            "num_trades": n_sells,
            "win_rate": (wins / n_sells) if n_sells else 0.0,
            "net_pnl": float(sells["realized_pnl"].sum()) if n_sells else 0.0,
            "median_hold_days": hold_days,
            "final_nav": float(result.nav["total_value"].iloc[-1]) if not result.nav.empty else initial_cash,
        },
        "n_buy": int((result.trades["side"] == OrderSide.BUY.value).sum()) if not result.trades.empty else 0,
        "data_hash": result.data_hash,
        "config_hash": result.config_hash,
    }


def with_params(base: HorizonParams, **changes) -> HorizonParams:
    return replace(base, **changes)


def _features(frame: pd.DataFrame):
    if len(frame) < WARMUP_BARS:
        return None
    close = frame["close"].astype(float).tolist()
    low = frame["low"].astype(float).tolist() if "low" in frame.columns else close
    weekday = pd.Timestamp(frame.index[-1]).weekday()
    return extract_features_from_arrays(close=close, low=low, weekday=int(weekday))


def _prepare(
    bars_by_symbol: Mapping[str, pd.DataFrame],
    start: Date,
    end: Date,
) -> dict[str, pd.DataFrame]:
    prepared: dict[str, pd.DataFrame] = {}
    for symbol, source in bars_by_symbol.items():
        frame = source.copy()
        if "date" in frame.columns:
            frame.index = pd.DatetimeIndex(pd.to_datetime(frame["date"]))
        elif not isinstance(frame.index, pd.DatetimeIndex):
            frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index))
        frame = frame.sort_index()
        frame = frame[frame.index.date <= end]
        if frame.empty:
            continue
        in_window = frame.index.date >= start
        locations = [i for i, value in enumerate(in_window) if value]
        if locations:
            frame = frame.iloc[max(0, locations[0] - WARMUP_BARS) :]
        if not frame.empty:
            prepared[symbol] = frame
    if not prepared:
        raise ValueError("指定窗口没有可用行情")
    return prepared


def _median_hold_days(trades: pd.DataFrame) -> float | None:
    if trades is None or trades.empty:
        return None
    buys = trades[trades["side"] == OrderSide.BUY.value].sort_values("trade_date")
    sells = trades[trades["side"] == OrderSide.SELL.value].sort_values("trade_date")
    if sells.empty or buys.empty:
        return None
    leftover = list(buys.itertuples(index=False))
    holds: list[int] = []
    for sell in sells.itertuples(index=False):
        match = None
        rest = []
        for buy in leftover:
            if match is None and buy.symbol == sell.symbol:
                match = buy
            else:
                rest.append(buy)
        leftover = rest
        if match is None:
            continue
        buy_d = pd.Timestamp(match.trade_date).date()
        sell_d = pd.Timestamp(sell.trade_date).date()
        holds.append((sell_d - buy_d).days)
    if not holds:
        return None
    holds.sort()
    mid = len(holds) // 2
    if len(holds) % 2:
        return float(holds[mid])
    return (holds[mid - 1] + holds[mid]) / 2.0
