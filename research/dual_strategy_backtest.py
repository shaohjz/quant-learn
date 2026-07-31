"""账户 #1/#3 策略与共享现金组合回测器的研究集成层。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date as Date
from datetime import timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from quant_core.buy_strategies import (
    Account1BuyInput,
    Account1BuyParams,
    ExistingPosition,
    SwingBuyInput,
    SwingBuyParams,
    evaluate_account1_buy_zone,
    evaluate_account3_swing,
)
from quant_core.domain import OrderSide
from quant_core.fees import FeeModel
from research.portfolio_backtest import (
    BacktestConfig,
    BacktestResult,
    StrategyCallback,
    StrategyContext,
    TradeRequest,
    run_portfolio_backtest,
)
from research.strategy_optimization import (
    EvaluationWindow,
    NestedWalkForwardEvaluator,
    StrategyOptimizationConfig,
)
from research.walk_forward import WalkForwardConfig

WARMUP_BARS = 30
BUY_BUDGET = 10_000.0
RESEARCH_DATA_WARNING = (
    "输入 CSV 未声明 adjustment_type=raw；仅按研究数据运行，成交价格可能受复权影响，结果不得用于生产或实盘判断。"
)

ACCOUNT1_CANDIDATES: tuple[dict[str, Any], ...] = (
    {"max_below_ma10_pct": None, "require_ma10_above_ma20": False, "min_expected_rr": 0.0},
    {"max_below_ma10_pct": 0.03, "require_ma10_above_ma20": False, "min_expected_rr": 1.0},
    {"max_below_ma10_pct": 0.05, "require_ma10_above_ma20": True, "min_expected_rr": 1.2},
    {"max_below_ma10_pct": 0.08, "require_ma10_above_ma20": True, "min_expected_rr": 1.5},
)
ACCOUNT3_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "a_ma20_tolerance": 0.015,
        "b_ma10_tolerance": 0.01,
        "max_volume_ratio": 0.8,
        "min_score": 5,
        "min_expected_rr": 1.2,
    },
    {
        "a_ma20_tolerance": 0.01,
        "b_ma10_tolerance": 0.008,
        "max_volume_ratio": 0.7,
        "min_score": 5,
        "min_expected_rr": 1.4,
    },
    {
        "a_ma20_tolerance": 0.02,
        "b_ma10_tolerance": 0.015,
        "max_volume_ratio": 0.8,
        "min_score": 7,
        "min_expected_rr": 1.2,
    },
    {
        "a_ma20_tolerance": 0.015,
        "b_ma10_tolerance": 0.01,
        "max_volume_ratio": 0.9,
        "min_score": 8,
        "min_expected_rr": 1.5,
    },
)


@dataclass(frozen=True)
class DataAudit:
    research_only: bool = False
    data_warning: str | None = None
    source_files: tuple[str, ...] = ()


def load_csv_directory(
    csv_directory: str | Path,
    *,
    allow_adjusted_research: bool = False,
) -> tuple[dict[str, pd.DataFrame], DataAudit]:
    """从目录加载多标的 CSV，并在默认模式严格要求显式 raw 标记。"""

    directory = Path(csv_directory)
    files = sorted(directory.glob("*.csv"))
    if not files:
        raise ValueError(f"CSV 目录中没有 .csv 文件: {directory}")

    bars: dict[str, pd.DataFrame] = {}
    research_only = False
    for path in files:
        frame = pd.read_csv(path)
        symbol = _symbol_from_frame(frame, path)
        if symbol in bars:
            raise ValueError(f"重复标的 CSV: {symbol}")
        if "adjustment_type" not in frame.columns:
            if not allow_adjusted_research:
                raise ValueError(
                    f"{path.name} 缺少 adjustment_type=raw；如仅作研究，请显式传入 --allow-adjusted-research"
                )
            research_only = True
            frame["adjustment_type"] = "raw"
        else:
            adjustment = frame["adjustment_type"].astype(str).str.lower()
            if not adjustment.eq("raw").all():
                if not allow_adjusted_research:
                    raise ValueError(f"{path.name} 必须全部声明 adjustment_type=raw")
                research_only = True
                # 组合执行器只接收 raw；此处转换只为运行研究，原始风险保留在 audit。
                frame["adjustment_type"] = "raw"
        bars[symbol] = _normalize_csv_frame(frame, path)

    return bars, DataAudit(
        research_only=research_only,
        data_warning=RESEARCH_DATA_WARNING if research_only else None,
        source_files=tuple(str(path) for path in files),
    )


def make_account1_strategy(
    params: Account1BuyParams | Mapping[str, Any] | None = None,
    *,
    trade_start: Date | None = None,
    trade_end: Date | None = None,
    buy_budget: float = BUY_BUDGET,
) -> StrategyCallback:
    """创建账户 #1 callback：MA10 买区，MA20-1.5ATR 止损或成本 +15% 止盈。"""

    resolved = _account1_params(params)
    _validate_budget(buy_budget)

    def strategy(context: StrategyContext) -> list[TradeRequest]:
        if not _inside_trade_window(context.date, trade_start, trade_end):
            return []
        requests: list[TradeRequest] = []
        market_change_pct = _cross_sectional_market_change(context)
        for symbol in sorted(context.bars):
            features = _features(context.bars[symbol])
            if features is None:
                continue
            position = context.positions.get(symbol)
            close = features["close"]
            if position is not None:
                stop = features["ma20"] - 1.5 * features["atr14"]
                target = position.avg_cost * 1.15
                if close <= stop or close >= target:
                    requests.append(
                        TradeRequest(
                            symbol,
                            OrderSide.SELL,
                            position.quantity,
                            "account1_exit:trend_break" if close <= stop else "account1_exit:cost_plus_15pct",
                        )
                    )
                continue

            risk = close - (features["ma20"] - 1.5 * features["atr14"])
            expected_rr = ((close * 1.15 - close) / risk) if risk > 0 else 0.0
            signal = evaluate_account1_buy_zone(
                Account1BuyInput(
                    symbol=symbol,
                    date=context.date,
                    close=close,
                    buy_zone=features["ma10"],
                    ma10=features["ma10"],
                    ma20=features["ma20"],
                    volume_ratio=features["today_volume_ratio"],
                    market_change_pct=market_change_pct,
                    expected_rr=expected_rr,
                    position=ExistingPosition(),
                ),
                resolved,
            )
            if signal.allowed:
                quantity = _budget_quantity(buy_budget, close)
                if quantity:
                    requests.append(TradeRequest(symbol, OrderSide.BUY, quantity, signal.reason))
        return requests

    return strategy


def make_account3_strategy(
    params: SwingBuyParams | Mapping[str, Any] | None = None,
    *,
    trade_start: Date | None = None,
    trade_end: Date | None = None,
    buy_budget: float = BUY_BUDGET,
) -> StrategyCallback:
    """创建账户 #3 callback：A/B 是唯一买型，生产 C-F 规则只贡献辅助分。"""

    resolved = _account3_params(params)
    _validate_budget(buy_budget)

    def strategy(context: StrategyContext) -> list[TradeRequest]:
        if not _inside_trade_window(context.date, trade_start, trade_end):
            return []
        requests: list[TradeRequest] = []
        for symbol in sorted(context.bars):
            features = _features(context.bars[symbol])
            if features is None:
                continue
            position = context.positions.get(symbol)
            close = features["close"]
            if position is not None:
                if close <= position.avg_cost * 0.95 or close >= position.avg_cost * 1.08:
                    requests.append(
                        TradeRequest(
                            symbol,
                            OrderSide.SELL,
                            position.quantity,
                            "account3_exit:cost_minus_5pct"
                            if close <= position.avg_cost * 0.95
                            else "account3_exit:cost_plus_8pct",
                        )
                    )
                continue

            signal = evaluate_account3_swing(
                SwingBuyInput(
                    symbol=symbol,
                    date=context.date,
                    close=close,
                    ma10=features["ma10"],
                    ma20=features["ma20"],
                    volume_ratio=features["today_volume_ratio"],
                    expected_rr=_swing_expected_rr(context.bars[symbol], features),
                    auxiliary_score=_auxiliary_cf_score(context.bars[symbol], features),
                ),
                resolved,
            )
            if signal.allowed:
                quantity = _budget_quantity(buy_budget, close)
                if quantity:
                    requests.append(TradeRequest(symbol, OrderSide.BUY, quantity, signal.reason))
        return requests

    return strategy


# 清晰的 callback 别名，供脚本或外部研究代码直接导入。
account1_strategy_callback = make_account1_strategy
account3_strategy_callback = make_account3_strategy


def run_dual_strategy_backtest(
    bars_by_symbol: Mapping[str, pd.DataFrame],
    *,
    start: Date | None = None,
    end: Date | None = None,
    account1_params: Account1BuyParams | Mapping[str, Any] | None = None,
    account3_params: SwingBuyParams | Mapping[str, Any] | None = None,
    backtest_config: BacktestConfig | None = None,
    data_audit: DataAudit | None = None,
) -> dict[str, Any]:
    """分别运行账户 #1 与 #3；两者各自复用同一个共享现金组合回测器。"""

    prepared = _prepare_window_data(bars_by_symbol, start, end)
    cfg = backtest_config or BacktestConfig()
    results = {
        "account1": run_portfolio_backtest(
            prepared,
            make_account1_strategy(account1_params, trade_start=start, trade_end=end),
            cfg,
        ),
        "account3": run_portfolio_backtest(
            prepared,
            make_account3_strategy(account3_params, trade_start=start, trade_end=end),
            cfg,
        ),
    }
    return {
        "mode": "baseline",
        "accounts": {name: backtest_result_to_dict(result) for name, result in results.items()},
        "audit": _combined_audit(data_audit, start, end),
    }


def optimize_dual_strategies(
    bars_by_symbol: Mapping[str, pd.DataFrame],
    *,
    start: Date,
    end: Date,
    holdout_start: Date | None = None,
    backtest_config: BacktestConfig | None = None,
    walk_forward: WalkForwardConfig | None = None,
    account1_candidates: Sequence[Mapping[str, Any]] = ACCOUNT1_CANDIDATES,
    account3_candidates: Sequence[Mapping[str, Any]] = ACCOUNT3_CANDIDATES,
    data_audit: DataAudit | None = None,
) -> dict[str, Any]:
    """用训练窗口选参、OOS 盲评并可选一次最终 holdout。"""

    if end < start:
        raise ValueError("end 不能早于 start")
    if holdout_start is not None and not start < holdout_start <= end:
        raise ValueError("holdout 必须位于 start 与 end 之间")
    cfg = backtest_config or BacktestConfig()
    wf = walk_forward or _default_walk_forward(start, end, holdout_start)
    data_hash = _frames_hash(bars_by_symbol)
    code_hash = _code_hash()

    def evaluate_account(
        account_id: int,
        candidates: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        def backtest(window: EvaluationWindow, params: Mapping[str, Any]) -> Mapping[str, Any]:
            prepared = _prepare_window_data(bars_by_symbol, window.start, window.end)
            callback = (
                make_account1_strategy(params, trade_start=window.start, trade_end=window.end)
                if account_id == 1
                else make_account3_strategy(params, trade_start=window.start, trade_end=window.end)
            )
            result = run_portfolio_backtest(prepared, callback, cfg)
            return _optimization_metrics(result, window)

        report = NestedWalkForwardEvaluator(
            StrategyOptimizationConfig(walk_forward=wf, min_trades=1),
            candidates,
            backtest,
        ).evaluate(data_hash=data_hash, code_hash=code_hash)
        return report.to_dict()

    return {
        "mode": "optimize",
        "accounts": {
            "account1": evaluate_account(1, account1_candidates),
            "account3": evaluate_account(3, account3_candidates),
        },
        "audit": {
            **_combined_audit(data_audit, start, end),
            "warmup_bars": WARMUP_BARS,
            "warmup_trading_allowed": False,
            "selection_policy": "training_only; OOS and holdout never select parameters",
            "market_filter_proxy": "cross_sectional_mean_return",
        },
    }


def backtest_result_to_dict(result: BacktestResult) -> dict[str, Any]:
    return {
        "metrics": asdict(result.metrics),
        "trades": _records(result.trades),
        "nav": _records(result.nav),
        "data_hash": result.data_hash,
        "config_hash": result.config_hash,
        "audit": result.audit,
    }


def _features(frame: pd.DataFrame) -> dict[str, float] | None:
    # 当前交易日不计入 warmup；必须先有完整 30 根历史。
    if len(frame) < WARMUP_BARS + 1:
        return None
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    avg_volume_5 = float(volume.iloc[-5:].mean())
    return {
        "close": float(close.iloc[-1]),
        "ma10": float(close.iloc[-10:].mean()),
        "ma20": float(close.iloc[-20:].mean()),
        "atr14": float(true_range.iloc[-14:].mean()),
        "today_volume_ratio": float(volume.iloc[-1] / avg_volume_5) if avg_volume_5 > 0 else 1.0,
        "change_pct": float(close.pct_change().iloc[-1] * 100),
    }


def _auxiliary_cf_score(frame: pd.DataFrame, features: Mapping[str, float]) -> int:
    """严格复刻生产 C-F 评分，但绝不把 C-F 变成独立可买 setup。"""

    close = frame["close"].astype(float)
    score = 0

    # C：布林下轨附近（生产规则中的既有指标）。
    ma20 = float(close.iloc[-20:].mean())
    lower = ma20 - 2 * float(close.iloc[-20:].std(ddof=0))
    if lower > 0 and features["close"] <= lower * 1.01:
        score += 3

    # D：RSI6 超卖（Wilder 初始平均的生产近似）。
    changes = close.diff().dropna().iloc[-6:]
    gains = float(changes.clip(lower=0).sum() / 6)
    losses = float((-changes.clip(upper=0)).sum() / 6)
    rsi6 = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    if rsi6 < 35:
        score += 3

    # E/F：连续下跌缩量企稳、单日大跌缩量。
    last_three = close.iloc[-3:].tolist()
    if (
        last_three[1] < last_three[0]
        and last_three[2] < last_three[1]
        and features["today_volume_ratio"] < 0.7
        and features["change_pct"] >= -1.5
    ):
        score += 4
    if features["change_pct"] < -2.0 and features["today_volume_ratio"] < 0.7:
        score += 2
    return score


def _cross_sectional_market_change(context: StrategyContext) -> float:
    """历史数据无指数列时，用当日横截面均值作为明确披露的弱市代理。"""

    changes: list[float] = []
    for frame in context.bars.values():
        if len(frame) < 2:
            continue
        close = frame["close"].astype(float)
        previous = float(close.iloc[-2])
        if previous > 0:
            changes.append((float(close.iloc[-1]) / previous - 1) * 100)
    return sum(changes) / len(changes) if changes else 0.0


def _swing_expected_rr(frame: pd.DataFrame, features: Mapping[str, float]) -> float:
    """按生产 swing_auto 的支撑/阻力与 100 股费用口径计算净盈亏比。"""

    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    price = features["close"]
    ma5 = float(close.iloc[-5:].mean())
    supports = [
        features["ma20"],
        features["ma10"],
        float(low.iloc[-5:].min()),
    ]
    valid_supports = [value for value in supports if value < price]
    support = max(valid_supports) if valid_supports else float(low.iloc[-5:].min())
    resistances = [
        ma5,
        features["ma10"],
        features["ma20"],
        float(high.iloc[-5:].max()),
    ]
    valid_resistances = [value for value in resistances if value > price]
    resistance = min(valid_resistances) if valid_resistances else float(high.iloc[-5:].max())
    downside = (price - support) / price if support < price else 0.01
    upside = (resistance - price) / price
    if downside <= 0:
        return 0.0

    trade_date = pd.Timestamp(frame.index[-1]).date()
    fee_model = FeeModel()
    buy_fees = fee_model.calculate("BUY", price * 100, trade_date=trade_date).total
    sell_fees = fee_model.calculate("SELL", resistance * 100, trade_date=trade_date).total
    fee_ratio = (buy_fees + sell_fees) / (price * 100)
    net_upside = upside - fee_ratio
    net_downside = downside + fee_ratio
    return net_upside / net_downside if net_downside > 0 else 0.0


def _prepare_window_data(
    bars_by_symbol: Mapping[str, pd.DataFrame],
    start: Date | None,
    end: Date | None,
) -> dict[str, pd.DataFrame]:
    prepared: dict[str, pd.DataFrame] = {}
    for symbol, source in bars_by_symbol.items():
        frame = source.copy()
        dates = _frame_dates(frame)
        frame.index = pd.DatetimeIndex(dates)
        frame = frame.sort_index()
        if end is not None:
            frame = frame[frame.index.date <= end]
        if start is not None and not frame.empty:
            in_window = frame.index.date >= start
            locations = [i for i, value in enumerate(in_window) if value]
            if locations:
                frame = frame.iloc[max(0, locations[0] - WARMUP_BARS) :]
            else:
                frame = frame.iloc[0:0]
        if not frame.empty:
            prepared[symbol] = frame
    if not prepared:
        raise ValueError("指定窗口没有可用行情")
    return prepared


def _optimization_metrics(result: BacktestResult, window: EvaluationWindow) -> dict[str, Any]:
    sells = result.trades[result.trades["side"] == OrderSide.SELL.value]
    num_trades = len(sells)
    realized = float(sells["realized_pnl"].sum()) if num_trades else 0.0
    fees = float(result.trades["total_fees"].sum()) if not result.trades.empty else 0.0
    return {
        "gross_expectancy": (realized + fees) / num_trades if num_trades else 0.0,
        "cost_per_trade": fees / num_trades if num_trades else 0.0,
        "num_trades": num_trades,
        "total_return": result.metrics.total_return,
        "window_kind": window.kind,
        "window_start": window.start,
        "window_end": window.end,
        "first_signal_date": (min(result.trades["signal_date"]).isoformat() if not result.trades.empty else None),
    }


def _default_walk_forward(start: Date, end: Date, holdout_start: Date | None) -> WalkForwardConfig:
    optimization_end = holdout_start - timedelta(days=1) if holdout_start else end
    available = (optimization_end - start).days
    if available < 45:
        raise ValueError("optimize 模式在 holdout 前至少需要 45 个自然日")
    train_days = max(30, available // 2)
    remaining = available - train_days
    purge_days = 1
    # 默认保留约三个完整 OOS 窗口，避免短窗噪声和无意义的大量重复搜索。
    oos_days = max(20, (remaining - purge_days) // 3)
    if train_days + purge_days + oos_days > available:
        train_days = available - purge_days - oos_days
    return WalkForwardConfig(
        start_date=start,
        end_date=optimization_end,
        train_window_days=train_days,
        oos_window_days=oos_days,
        purge_days=purge_days,
        step_days=oos_days,
        holdout_start=holdout_start,
        holdout_end=end if holdout_start else None,
    )


def _account1_params(
    params: Account1BuyParams | Mapping[str, Any] | None,
) -> Account1BuyParams:
    if params is None:
        return Account1BuyParams()
    if isinstance(params, Account1BuyParams):
        return params
    allowed = {"max_below_ma10_pct", "require_ma10_above_ma20", "min_expected_rr"}
    _reject_unknown_params(params, allowed, 1)
    return replace(Account1BuyParams(), **dict(params))


def _account3_params(params: SwingBuyParams | Mapping[str, Any] | None) -> SwingBuyParams:
    if params is None:
        return SwingBuyParams()
    if isinstance(params, SwingBuyParams):
        return params
    allowed = {
        "a_ma20_tolerance",
        "b_ma10_tolerance",
        "max_volume_ratio",
        "min_score",
        "min_expected_rr",
    }
    _reject_unknown_params(params, allowed, 3)
    return replace(SwingBuyParams(), **dict(params))


def _reject_unknown_params(params: Mapping[str, Any], allowed: set[str], account_id: int) -> None:
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"账户 #{account_id} 禁止的参数/指标: {sorted(unknown)}")


def _normalize_csv_frame(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    missing = {"open", "high", "low", "close", "volume"} - set(frame.columns)
    if missing:
        raise ValueError(f"{path.name} 缺少行情列: {sorted(missing)}")
    if "date" not in frame.columns and "timestamp" not in frame.columns:
        raise ValueError(f"{path.name} 缺少 date 或 timestamp")
    return frame.drop(columns=["symbol", "code"], errors="ignore")


def _symbol_from_frame(frame: pd.DataFrame, path: Path) -> str:
    for column in ("symbol", "code"):
        if column in frame.columns:
            values = frame[column].dropna().astype(str).unique()
            if len(values) != 1:
                raise ValueError(f"{path.name} 的 {column} 必须只有一个标的")
            return values[0].strip()
    return path.stem


def _frame_dates(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if "date" in frame.columns:
        return pd.DatetimeIndex(pd.to_datetime(frame["date"]))
    if "timestamp" in frame.columns:
        return pd.DatetimeIndex(pd.to_datetime(frame["timestamp"]))
    return pd.DatetimeIndex(pd.to_datetime(frame.index))


def _inside_trade_window(current: Date, start: Date | None, end: Date | None) -> bool:
    return (start is None or current >= start) and (end is None or current <= end)


def _budget_quantity(budget: float, price: float) -> int:
    return int(budget / price / 100) * 100


def _validate_budget(budget: float) -> None:
    if budget <= 0:
        raise ValueError("buy_budget 必须为正数")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _combined_audit(
    data_audit: DataAudit | None,
    start: Date | None,
    end: Date | None,
) -> dict[str, Any]:
    audit = data_audit or DataAudit()
    return {
        **asdict(audit),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "buy_budget": BUY_BUDGET,
        "warmup_bars": WARMUP_BARS,
        "warmup_trading_allowed": False,
        "market_filter_proxy": "cross_sectional_mean_return",
    }


def _frames_hash(bars_by_symbol: Mapping[str, pd.DataFrame]) -> str:
    digest = hashlib.sha256()
    for symbol in sorted(bars_by_symbol):
        digest.update(symbol.encode())
        digest.update(pd.util.hash_pandas_object(bars_by_symbol[symbol], index=True).values.tobytes())
    return digest.hexdigest()


def _code_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
