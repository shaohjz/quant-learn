"""日频多标的共享现金回测器。

策略 callback 在每日收盘后接收 :class:`StrategyContext`，返回 ``TradeRequest``
（或等价字典）。请求只会在该标的下一根可用日线，以未复权开盘价成交。
特征计算完全由 callback 负责；本模块只处理执行、费用、组合约束与审计。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import date as Date
from datetime import datetime, time
from typing import Any

import pandas as pd

from quant_core.domain import AdjustmentType, Bar, OrderIntent, OrderSide, OrderType, PriceSource
from quant_core.execution import ExecutionConfig, ExecutionPolicy
from quant_core.fees import FeeModel
from quant_core.metrics import (
    PerformanceMetrics,
    calc_max_drawdown,
    calc_sharpe,
    calc_sortino,
)


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    max_positions: int = 6
    max_position_pct: float = 0.20
    max_daily_new_positions: int = 3
    lot_size: int = 100
    slippage_pct: float = 0.0
    cost_multiplier: float = 1.0
    volume_participation: float = 0.05
    risk_free_rate: float = 0.02

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if self.max_positions <= 0 or self.max_daily_new_positions < 0:
            raise ValueError("position limits must be non-negative")
        if not 0 < self.max_position_pct <= 1:
            raise ValueError("max_position_pct must be in (0, 1]")
        if self.lot_size <= 0 or self.slippage_pct < 0:
            raise ValueError("lot_size must be positive and slippage_pct non-negative")
        if self.cost_multiplier < 0:
            raise ValueError("cost_multiplier must be non-negative")
        if not 0 < self.volume_participation <= 1:
            raise ValueError("volume_participation must be in (0, 1]")


@dataclass(frozen=True)
class TradeRequest:
    """策略在 T 日收盘后产生的交易请求。

    ``quantity`` 是期望成交股数。买入会向下取整至 ``lot_size``；卖出最多
    卖出当日开盘前已有的可用持仓。
    """

    symbol: str
    side: OrderSide | str
    quantity: int
    reason: str = ""


@dataclass(frozen=True)
class PositionView:
    quantity: int
    avg_cost: float
    last_price: float


@dataclass(frozen=True)
class StrategyContext:
    date: Date
    bars: Mapping[str, pd.DataFrame]
    cash: float
    positions: Mapping[str, PositionView]
    nav: float


@dataclass(frozen=True)
class TradeRecord:
    symbol: str
    side: str
    signal_date: Date
    trade_date: Date
    quantity: int
    price: float
    amount: float
    commission: float
    stamp_tax: float
    transfer_fee: float
    total_fees: float
    cash_after: float
    price_source: str
    reason: str = ""
    realized_pnl: float = 0.0


@dataclass
class BacktestResult:
    trades: pd.DataFrame
    nav: pd.DataFrame
    metrics: PerformanceMetrics
    data_hash: str
    config_hash: str
    audit: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Position:
    quantity: int
    avg_cost: float


@dataclass(frozen=True)
class _PendingRequest:
    request: TradeRequest
    signal_date: Date


StrategyCallback = Callable[[StrategyContext], Iterable[TradeRequest | Mapping[str, Any]] | None]

_BAR_COLUMNS = ("open", "high", "low", "close", "volume")
_TRADE_COLUMNS = list(TradeRecord.__dataclass_fields__)
_NAV_COLUMNS = ["date", "cash", "market_value", "total_value", "positions", "integrity_error"]


def run_portfolio_backtest(
    bars_by_symbol: Mapping[str, pd.DataFrame | Iterable[Bar | Mapping[str, Any]]],
    strategy: StrategyCallback,
    config: BacktestConfig | None = None,
    fee_model: FeeModel | None = None,
) -> BacktestResult:
    """运行共享现金组合回测。

    DataFrame 必须以日期索引，或包含 ``date``/``timestamp`` 列，并含
    ``open/high/low/close/volume``。这些 OHLC 必须是未复权价格；若提供
    ``adjustment_type``，其值必须是 ``raw``。
    """

    cfg = config or BacktestConfig()
    normalized = _normalize_bars(bars_by_symbol)
    if not normalized:
        raise ValueError("bars_by_symbol must not be empty")

    model = fee_model or FeeModel()
    policy = ExecutionPolicy(
        ExecutionConfig(
            default_price_source=PriceSource.NEXT_OPEN,
            allow_same_bar=False,
            slippage_pct=cfg.slippage_pct,
            volume_participation=cfg.volume_participation,
            min_trade_unit=cfg.lot_size,
        ),
        fee_model=model,
    )
    dates = sorted({d for rows in normalized.values() for d in rows})
    history_frames = {symbol: _history_frame(rows, max(rows)) for symbol, rows in normalized.items()}
    cash = float(cfg.initial_cash)
    positions: dict[str, _Position] = {}
    last_prices: dict[str, float] = {}
    pending: list[_PendingRequest] = []
    trade_records: list[TradeRecord] = []
    nav_records: list[dict[str, Any]] = []

    for current_date in dates:
        todays_bars = {symbol: rows[current_date] for symbol, rows in normalized.items() if current_date in rows}
        opening_available = {symbol: pos.quantity for symbol, pos in positions.items()}
        new_positions_today = 0

        due = [item for item in pending if item.signal_date < current_date and item.request.symbol in todays_bars]
        pending = [item for item in pending if item not in due]
        due.sort(key=lambda item: (0 if _side(item.request.side) == OrderSide.SELL else 1, item.request.symbol))

        for item in due:
            request = item.request
            symbol = request.symbol
            side = _side(request.side)
            bar = todays_bars[symbol]
            quantity = int(request.quantity)
            if quantity <= 0:
                continue

            if side == OrderSide.SELL:
                quantity = min(quantity, opening_available.get(symbol, 0))
            else:
                quantity = (quantity // cfg.lot_size) * cfg.lot_size
                is_new = symbol not in positions
                if is_new and (
                    len(positions) >= cfg.max_positions or new_positions_today >= cfg.max_daily_new_positions
                ):
                    continue
                pretrade_nav = _portfolio_value(cash, positions, last_prices, todays_bars)
                existing_value = positions.get(symbol, _Position(0, 0.0)).quantity * bar.open
                max_add_value = max(pretrade_nav * cfg.max_position_pct - existing_value, 0.0)
                quantity = min(quantity, int(max_add_value / _buy_price(bar.open, cfg.slippage_pct)))
                quantity = (quantity // cfg.lot_size) * cfg.lot_size

            if quantity <= 0:
                continue
            intent = OrderIntent(
                symbol=symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=quantity,
                price=bar.open,
                signal_time=datetime.combine(item.signal_date, time(15, 0)),
                submit_time=datetime.combine(current_date, time(9, 25)),
            )
            fill = policy.execute(
                intent,
                next_bar=bar,
                portfolio_holdings={s: p.quantity for s, p in positions.items()},
                signal_date=item.signal_date,
                trade_date=current_date,
            )
            if fill is None:
                continue

            if side == OrderSide.BUY:
                fill = _fit_buy_to_cash(policy, intent, bar, item.signal_date, current_date, positions, cash, cfg)
                if fill is None:
                    continue

            commission = round(fill.commission * cfg.cost_multiplier, 2)
            stamp_tax = round(fill.stamp_tax * cfg.cost_multiplier, 2)
            transfer_fee = round(fill.transfer_fee * cfg.cost_multiplier, 2)
            total_fees = round(commission + stamp_tax + transfer_fee, 2)
            realized_pnl = 0.0

            if side == OrderSide.BUY:
                total_cost = fill.amount + total_fees
                if total_cost > cash + 1e-9:
                    continue
                was_new = symbol not in positions
                old = positions.get(symbol, _Position(0, 0.0))
                new_qty = old.quantity + fill.quantity
                avg_cost = (old.avg_cost * old.quantity + total_cost) / new_qty
                positions[symbol] = _Position(new_qty, avg_cost)
                cash -= total_cost
                if was_new:
                    new_positions_today += 1
            else:
                old = positions.get(symbol)
                if old is None:
                    continue
                opening_available[symbol] = max(opening_available.get(symbol, 0) - fill.quantity, 0)
                realized_pnl = fill.amount - total_fees - old.avg_cost * fill.quantity
                cash += fill.amount - total_fees
                remaining = old.quantity - fill.quantity
                if remaining > 0:
                    positions[symbol] = _Position(remaining, old.avg_cost)
                else:
                    positions.pop(symbol, None)

            cash = round(cash, 10)
            trade_records.append(
                TradeRecord(
                    symbol=symbol,
                    side=side.value,
                    signal_date=item.signal_date,
                    trade_date=current_date,
                    quantity=fill.quantity,
                    price=fill.price,
                    amount=fill.amount,
                    commission=commission,
                    stamp_tax=stamp_tax,
                    transfer_fee=transfer_fee,
                    total_fees=total_fees,
                    cash_after=cash,
                    price_source=fill.price_source.value,
                    reason=request.reason,
                    realized_pnl=round(realized_pnl, 2),
                )
            )

        for symbol, bar in todays_bars.items():
            last_prices[symbol] = bar.close
        market_value = sum(pos.quantity * last_prices[symbol] for symbol, pos in positions.items())
        total_value = cash + market_value
        nav_records.append(
            {
                "date": current_date,
                "cash": cash,
                "market_value": market_value,
                "total_value": total_value,
                "positions": len(positions),
                "integrity_error": total_value - cash - market_value,
            }
        )

        context = StrategyContext(
            date=current_date,
            bars={
                symbol: history_frames[symbol].loc[:current_date]
                for symbol, rows in normalized.items()
                if rows and min(rows) <= current_date
            },
            cash=cash,
            positions={
                symbol: PositionView(pos.quantity, pos.avg_cost, last_prices[symbol])
                for symbol, pos in positions.items()
            },
            nav=total_value,
        )
        generated = strategy(context)
        if generated:
            for raw_request in generated:
                request = _coerce_request(raw_request)
                if request.symbol not in normalized:
                    raise ValueError(f"strategy requested unknown symbol: {request.symbol}")
                pending.append(_PendingRequest(request, current_date))

    trades = pd.DataFrame([asdict(record) for record in trade_records], columns=_TRADE_COLUMNS)
    nav = pd.DataFrame(nav_records, columns=_NAV_COLUMNS)
    metrics = _calculate_metrics(nav, trades, cfg)
    data_hash = _data_hash(normalized)
    config_hash = _json_hash(asdict(cfg))
    return BacktestResult(
        trades=trades,
        nav=nav,
        metrics=metrics,
        data_hash=data_hash,
        config_hash=config_hash,
        audit={
            "price_source": PriceSource.NEXT_OPEN.value,
            "adjustment_type": AdjustmentType.RAW.value,
            "same_bar_allowed": False,
            "fee_model": type(model).__name__,
            "cost_multiplier": cfg.cost_multiplier,
            "slippage_pct": cfg.slippage_pct,
            "symbols": sorted(normalized),
            "start_date": dates[0].isoformat(),
            "end_date": dates[-1].isoformat(),
            "unfilled_requests_at_end": len(pending),
        },
    )


def _normalize_bars(
    bars_by_symbol: Mapping[str, pd.DataFrame | Iterable[Bar | Mapping[str, Any]]],
) -> dict[str, dict[Date, Bar]]:
    result: dict[str, dict[Date, Bar]] = {}
    for symbol, source in bars_by_symbol.items():
        if isinstance(source, pd.DataFrame):
            frame = source.copy()
            missing = set(_BAR_COLUMNS) - set(frame.columns)
            if missing:
                raise ValueError(f"{symbol} missing bar columns: {sorted(missing)}")
            if "date" in frame.columns:
                raw_dates = frame.pop("date")
            elif "timestamp" in frame.columns:
                raw_dates = frame["timestamp"]
            else:
                raw_dates = frame.index
            entries: list[Bar] = []
            for (_, row), raw_date in zip(frame.iterrows(), raw_dates):
                adjustment = str(row.get("adjustment_type", "raw")).lower()
                if adjustment not in ("raw", "adjustmenttype.raw"):
                    raise ValueError(f"{symbol} execution OHLC must be unadjusted/raw")
                timestamp = pd.Timestamp(raw_date).to_pydatetime()
                entries.append(
                    Bar(
                        symbol=symbol,
                        exchange=str(row.get("exchange", _infer_exchange(symbol))),
                        timestamp=timestamp,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                        amount=float(row.get("amount", 0.0)),
                        adjustment_type=AdjustmentType.RAW,
                        source=str(row.get("source", "portfolio_backtest_input")),
                    )
                )
        else:
            entries = []
            for value in source:
                if isinstance(value, Bar):
                    if value.adjustment_type != AdjustmentType.RAW:
                        raise ValueError(f"{symbol} execution OHLC must be unadjusted/raw")
                    entries.append(value)
                else:
                    adjustment = str(value.get("adjustment_type", "raw")).lower()
                    if adjustment not in ("raw", "adjustmenttype.raw"):
                        raise ValueError(f"{symbol} execution OHLC must be unadjusted/raw")
                    raw_date = value.get("timestamp", value.get("date"))
                    if raw_date is None:
                        raise ValueError(f"{symbol} bar requires date or timestamp")
                    entries.append(
                        Bar(
                            symbol=symbol,
                            exchange=str(value.get("exchange", _infer_exchange(symbol))),
                            timestamp=pd.Timestamp(raw_date).to_pydatetime(),
                            open=float(value["open"]),
                            high=float(value["high"]),
                            low=float(value["low"]),
                            close=float(value["close"]),
                            volume=float(value["volume"]),
                            amount=float(value.get("amount", 0.0)),
                            adjustment_type=AdjustmentType.RAW,
                            source=str(value.get("source", "portfolio_backtest_input")),
                        )
                    )
        rows: dict[Date, Bar] = {}
        for bar in entries:
            day = bar.timestamp.date()
            if day in rows:
                raise ValueError(f"{symbol} has duplicate daily bar: {day}")
            if min(bar.open, bar.high, bar.low, bar.close) <= 0 or bar.volume < 0:
                raise ValueError(f"{symbol} has invalid OHLCV on {day}")
            rows[day] = bar
        if rows:
            result[symbol] = dict(sorted(rows.items()))
    return result


def _history_frame(rows: Mapping[Date, Bar], end_date: Date) -> pd.DataFrame:
    values = [
        {
            "date": day,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "amount": bar.amount,
            "exchange": bar.exchange,
            "adjustment_type": bar.adjustment_type.value,
            "source": bar.source,
        }
        for day, bar in rows.items()
        if day <= end_date
    ]
    return pd.DataFrame(values).set_index("date")


def _coerce_request(value: TradeRequest | Mapping[str, Any]) -> TradeRequest:
    if isinstance(value, TradeRequest):
        return replace(value, side=_side(value.side))
    return TradeRequest(
        symbol=str(value["symbol"]),
        side=_side(value["side"]),
        quantity=int(value["quantity"]),
        reason=str(value.get("reason", "")),
    )


def _side(value: OrderSide | str) -> OrderSide:
    if isinstance(value, OrderSide):
        return value
    return OrderSide(str(value).upper())


def _fit_buy_to_cash(
    policy: ExecutionPolicy,
    intent: OrderIntent,
    bar: Bar,
    signal_date: Date,
    trade_date: Date,
    positions: Mapping[str, _Position],
    cash: float,
    cfg: BacktestConfig,
):
    quantity = intent.quantity
    while quantity >= cfg.lot_size:
        candidate = policy.execute(
            replace(intent, quantity=quantity),
            next_bar=bar,
            portfolio_holdings={s: p.quantity for s, p in positions.items()},
            signal_date=signal_date,
            trade_date=trade_date,
        )
        if candidate is None:
            return None
        fees = (candidate.commission + candidate.stamp_tax + candidate.transfer_fee) * cfg.cost_multiplier
        if candidate.amount + fees <= cash + 1e-9:
            return candidate
        quantity -= cfg.lot_size
    return None


def _portfolio_value(
    cash: float,
    positions: Mapping[str, _Position],
    last_prices: Mapping[str, float],
    todays_bars: Mapping[str, Bar],
) -> float:
    value = cash
    for symbol, position in positions.items():
        price = todays_bars[symbol].open if symbol in todays_bars else last_prices[symbol]
        value += position.quantity * price
    return value


def _buy_price(open_price: float, slippage_pct: float) -> float:
    return open_price * (1 + slippage_pct)


def _infer_exchange(symbol: str) -> str:
    return "SH" if symbol.startswith(("5", "6", "9")) else "SZ"


def _data_hash(normalized: Mapping[str, Mapping[Date, Bar]]) -> str:
    records = []
    for symbol in sorted(normalized):
        for day, bar in normalized[symbol].items():
            records.append(
                [
                    symbol,
                    day.isoformat(),
                    bar.exchange,
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                    bar.amount,
                    bar.source,
                ]
            )
    return _json_hash(records)


def _json_hash(value: Any) -> str:
    content = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _calculate_metrics(
    nav: pd.DataFrame,
    trades: pd.DataFrame,
    cfg: BacktestConfig,
) -> PerformanceMetrics:
    values = nav["total_value"].astype(float).tolist()
    returns = nav["total_value"].pct_change().dropna().astype(float).tolist()
    total_return = values[-1] / cfg.initial_cash - 1 if values else 0.0
    years = max((len(values) - 1) / 252, 0.0)
    cagr = (values[-1] / cfg.initial_cash) ** (1 / years) - 1 if years > 0 and values[-1] > 0 else 0.0
    volatility = pd.Series(returns).std(ddof=1) * math.sqrt(252) if len(returns) >= 2 else 0.0
    max_drawdown = calc_max_drawdown(values)
    sells = trades[trades["side"] == OrderSide.SELL.value] if not trades.empty else trades
    pnls = sells["realized_pnl"].astype(float).tolist() if not sells.empty else []
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    win_rate = len(wins) / len(pnls) if pnls else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_loss = abs(sum(losses))
    total_fees = float(trades["total_fees"].sum()) if not trades.empty else 0.0
    turnover = float(trades["amount"].sum()) / cfg.initial_cash if not trades.empty else 0.0
    return PerformanceMetrics(
        total_return=total_return,
        cagr=cagr,
        annual_volatility=float(volatility),
        sharpe_ratio=calc_sharpe(returns, cfg.risk_free_rate),
        sortino_ratio=calc_sortino(returns, cfg.risk_free_rate),
        calmar_ratio=cagr / max_drawdown if max_drawdown > 0 else 0.0,
        max_drawdown=max_drawdown,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=sum(wins) / gross_loss if gross_loss > 0 else 0.0,
        net_expectancy=sum(pnls) / len(pnls) if pnls else 0.0,
        total_trades=len(trades),
        turnover=turnover,
        total_fees=total_fees,
    )
