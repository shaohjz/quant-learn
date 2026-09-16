"""生产侧中长线扫描与最短持有期。供 swing_daily / Pulse 调用。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from quant_core.horizon import HorizonParams, load_horizon
from quant_core.position_strategies import (
    evaluate_position_buy,
    evaluate_position_sell,
    extract_features_from_arrays,
)


def features_from_klines(klines: list[dict], *, as_of: date | None = None) -> Any:
    if not klines:
        return None
    close = [float(k["close"]) for k in klines]
    low = [float(k.get("low", k["close"])) for k in klines]
    last = klines[-1]
    raw_date = last.get("date") or (as_of.isoformat() if as_of else None)
    weekday = 0
    if raw_date:
        weekday = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d").weekday()
    elif as_of:
        weekday = as_of.weekday()
    return extract_features_from_arrays(close=close, low=low, weekday=weekday)


def scan_code_horizon(
    code: str,
    name: str,
    klines: list[dict],
    quote_price: float,
    params: HorizonParams,
    *,
    as_of: date | None = None,
) -> dict | None:
    """把中长线买点转成 swing_daily pick_buys 能吃的行。"""

    features = features_from_klines(klines, as_of=as_of)
    if features is None:
        return None
    if quote_price and quote_price > 0:
        patched = list(klines)
        last = dict(patched[-1])
        last["close"] = quote_price
        last["low"] = min(float(last.get("low", quote_price)), quote_price)
        patched[-1] = last
        features = features_from_klines(patched, as_of=as_of)
        if features is None:
            return None
    decision = evaluate_position_buy(features, params, as_of=as_of)
    if not decision.allowed:
        return None
    stop = round(quote_price * (1.0 - params.stop_loss_pct), 2)
    target = round(quote_price * (1.0 + params.take_profit_pct), 2)
    rr = params.take_profit_pct / params.stop_loss_pct if params.stop_loss_pct else 0.0
    return {
        "name": name,
        "code": code,
        "price": round(float(quote_price), 2),
        "signals": [(decision.reason, 6)],
        "signal_type": "G",
        "score": 6,
        "support": stop,
        "resist": target,
        "support_name": "灾难止损",
        "resist_name": "止盈",
        "net_rr": round(rr, 2),
        "risk_reward": round(rr, 2),
        "upside_pct": round(params.take_profit_pct * 100, 2),
        "downside_pct": round(params.stop_loss_pct * 100, 2),
    }


def hold_days_from_trades(rows: list[tuple[str, str]], today: date) -> int:
    """rows: (trade_date, direction) 按时间升序。用最后一次开仓日起算。"""

    last_buy: date | None = None
    qty_proxy = 0
    for raw_d, direction in rows:
        d = datetime.strptime(str(raw_d)[:10], "%Y-%m-%d").date()
        side = str(direction or "").upper()
        if side == "BUY":
            if qty_proxy <= 0:
                last_buy = d
            qty_proxy += 1
        elif side == "SELL":
            qty_proxy = max(0, qty_proxy - 1)
            if qty_proxy <= 0:
                last_buy = None
    if last_buy is None:
        return 0
    return (today - last_buy).days


def allow_sell(
    *,
    params: HorizonParams,
    klines: list[dict],
    avg_cost: float,
    held_days: int,
    quote_price: float | None = None,
    as_of: date | None = None,
) -> tuple[bool, str, str]:
    """返回 (该卖?, reason_code, reason)。无特征时只看成本和最短持有。"""

    features = features_from_klines(klines, as_of=as_of)
    if features is None:
        if quote_price and quote_price <= avg_cost * (1.0 - params.stop_loss_pct):
            return True, "DISASTER_STOP", "无K线，按成本灾难止损"
        if held_days < params.min_hold_days:
            return False, "MIN_HOLD", f"已持有 {held_days} 日"
        if quote_price and quote_price >= avg_cost * (1.0 + params.take_profit_pct):
            return True, "TAKE_PROFIT", "无K线，按成本止盈"
        return False, "HOLD", "无足够K线"
    if quote_price and quote_price > 0:
        from dataclasses import replace

        features = replace(features, close=float(quote_price))
    decision = evaluate_position_sell(
        features=features,
        params=params,
        avg_cost=avg_cost,
        held_days=held_days,
    )
    return decision.allowed, decision.reason_code, decision.reason
