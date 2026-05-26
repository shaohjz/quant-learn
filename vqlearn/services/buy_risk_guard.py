"""
vqlearn/services/buy_risk_guard.py — REQ-028 买入防接飞刀风控

集中实现买入前置过滤，供实盘/模拟策略层统一调用：
1. 大盘情绪熔断：主要指数跌幅 <= -1%，或全市场下跌家数占比 >= 80%，暂停抄底买入。
2. 单票开盘暴跌禁买：开盘跌幅超过 5%，且放量、跌破支撑位时，当日坚决不买。

设计目标：
- 线上尽量使用实时行情；行情接口不可用时不误杀，只返回不可判定原因。
- 纯函数可注入参数，方便测试和复盘验收。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any, Callable


@dataclass(frozen=True)
class RiskDecision:
    blocked: bool
    reason: str
    details: dict[str, Any]


_MARKET_CACHE: tuple[datetime, RiskDecision] | None = None
_MARKET_CACHE_SECONDS = 60


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _trading_minutes_elapsed(now: datetime | None = None) -> float:
    """A 股当前交易日已进行分钟数，最多 240。"""
    now = now or datetime.now()
    t = now.time()
    if t < time(9, 30):
        return 0.0
    if t <= time(11, 30):
        return float((t.hour - 9) * 60 + t.minute - 30)
    if t < time(13, 0):
        return 120.0
    if t <= time(15, 0):
        return float(120 + (t.hour - 13) * 60 + t.minute)
    return 240.0


def evaluate_market_panic(
    *,
    index_changes_pct: dict[str, float] | None = None,
    declining_count: int | None = None,
    total_count: int | None = None,
    index_drop_threshold_pct: float = -1.0,
    breadth_decline_ratio_threshold: float = 0.80,
) -> RiskDecision:
    """判断是否触发大盘情绪熔断。

    规则：
    - 任一主要指数跌幅 <= -1%，触发；
    - 或全市场下跌家数 / 有效股票数 >= 80%，触发。
    """
    details: dict[str, Any] = {
        "index_changes_pct": index_changes_pct or {},
        "declining_count": declining_count,
        "total_count": total_count,
        "index_drop_threshold_pct": index_drop_threshold_pct,
        "breadth_decline_ratio_threshold": breadth_decline_ratio_threshold,
    }

    if index_changes_pct:
        for name, pct in index_changes_pct.items():
            pct = _safe_float(pct)
            if pct <= index_drop_threshold_pct:
                return RiskDecision(
                    True,
                    f"大盘情绪熔断：{name} 跌幅 {pct:.2f}% <= {index_drop_threshold_pct:.2f}%",
                    {**details, "trigger": "index", "trigger_index": name, "trigger_pct": pct},
                )

    if declining_count is not None and total_count:
        ratio = declining_count / max(total_count, 1)
        details["decline_ratio"] = ratio
        if ratio >= breadth_decline_ratio_threshold:
            return RiskDecision(
                True,
                f"大盘情绪熔断：全市场下跌家数占比 {ratio:.1%} >= {breadth_decline_ratio_threshold:.0%}",
                {**details, "trigger": "breadth"},
            )

    return RiskDecision(False, "大盘情绪正常", details)


def fetch_market_panic_snapshot() -> RiskDecision:
    """拉实时行情判断大盘熔断。

    优先使用 akshare：
    - stock_zh_index_spot_em：主要宽基指数涨跌幅；
    - stock_zh_a_spot_em：全市场上涨/下跌家数。

    接口失败时返回 blocked=False，避免数据源异常导致误杀交易；调用方会记录原因。
    """
    index_changes: dict[str, float] = {}
    declining_count: int | None = None
    total_count: int | None = None

    try:
        import akshare as ak  # type: ignore
        import pandas as pd  # noqa: F401  # type: ignore

        # 主要指数：上证指数、深证成指、创业板指、沪深300。
        try:
            idx = ak.stock_zh_index_spot_em()
            code_col = "代码" if "代码" in idx.columns else "code"
            name_col = "名称" if "名称" in idx.columns else "name"
            pct_col = "涨跌幅" if "涨跌幅" in idx.columns else "pct_chg"
            major_codes = {"000001", "399001", "399006", "000300"}
            for _, row in idx.iterrows():
                code = str(row.get(code_col, ""))
                if code in major_codes:
                    name = str(row.get(name_col, code))
                    index_changes[name] = _safe_float(row.get(pct_col))
        except Exception:
            pass

        try:
            spot = ak.stock_zh_a_spot_em()
            pct_col = "涨跌幅" if "涨跌幅" in spot.columns else "pct_chg"
            pct = spot[pct_col].apply(_safe_float)
            total_count = int(pct.notna().sum())
            declining_count = int((pct < 0).sum())
        except Exception:
            pass
    except Exception as exc:
        return RiskDecision(False, f"大盘情绪数据不可用：{exc}", {"data_available": False})

    if not index_changes and (declining_count is None or not total_count):
        return RiskDecision(False, "大盘情绪数据不可用", {"data_available": False})

    decision = evaluate_market_panic(
        index_changes_pct=index_changes,
        declining_count=declining_count,
        total_count=total_count,
    )
    decision.details["data_available"] = True
    return decision


def get_market_panic_decision(fetcher: Callable[[], RiskDecision] | None = None) -> RiskDecision:
    """带 60 秒缓存的大盘熔断检查，避免每只股票每个 tick 都打实时接口。"""
    global _MARKET_CACHE
    now = datetime.now()
    if _MARKET_CACHE is not None:
        ts, cached = _MARKET_CACHE
        if (now - ts).total_seconds() < _MARKET_CACHE_SECONDS:
            return cached

    fetcher = fetcher or fetch_market_panic_snapshot
    decision = fetcher()
    _MARKET_CACHE = (now, decision)
    return decision


def evaluate_opening_crash_filter(
    *,
    code: str,
    current_price: float,
    open_price: float,
    prev_close: float,
    low_price: float | None = None,
    support_level: float | None = None,
    current_volume: float | None = None,
    avg_vol_5d: float | None = None,
    now: datetime | None = None,
    open_drop_threshold_pct: float = -5.0,
    volume_spike_multiplier: float = 1.5,
) -> RiskDecision:
    """判断单票是否触发“开盘放量暴跌砸穿支撑，当日禁买”。

    触发条件（同时满足）：
    1. 开盘价较昨收跌幅 <= -5%；
    2. 当前价/最低价已经跌破支撑位；
    3. 当前累计成交量相对 5 日均量的时间进度口径 >= 1.5 倍（放量）。

    若缺少昨收、开盘价、5日均量等关键数据，则不误杀，返回 blocked=False 并说明原因。
    """
    current_price = _safe_float(current_price)
    open_price = _safe_float(open_price)
    prev_close = _safe_float(prev_close)
    low = _safe_float(low_price, current_price) or current_price
    support = _safe_float(support_level)
    cur_vol = _safe_float(current_volume)
    avg_vol = _safe_float(avg_vol_5d)

    details: dict[str, Any] = {
        "code": code,
        "current_price": current_price,
        "open_price": open_price,
        "prev_close": prev_close,
        "low_price": low,
        "support_level": support,
        "current_volume": cur_vol,
        "avg_vol_5d": avg_vol,
        "open_drop_threshold_pct": open_drop_threshold_pct,
        "volume_spike_multiplier": volume_spike_multiplier,
    }

    if prev_close <= 0 or open_price <= 0:
        return RiskDecision(False, "暴跌过滤跳过：缺少昨收/开盘价", details)

    open_drop_pct = (open_price / prev_close - 1.0) * 100.0
    details["open_drop_pct"] = open_drop_pct
    if open_drop_pct > open_drop_threshold_pct:
        return RiskDecision(False, "未触发开盘暴跌", details)

    if support <= 0:
        return RiskDecision(False, "暴跌过滤跳过：缺少支撑位", details)

    broke_support = min(current_price, low) <= support
    details["broke_support"] = broke_support
    if not broke_support:
        return RiskDecision(False, "开盘暴跌但未砸穿支撑位", details)

    if cur_vol <= 0 or avg_vol <= 0:
        return RiskDecision(False, "暴跌过滤跳过：缺少成交量/5日均量", details)

    elapsed = max(_trading_minutes_elapsed(now), 5.0)
    expected_volume = avg_vol * (elapsed / 240.0)
    volume_ratio = cur_vol / max(expected_volume, 1.0)
    details["elapsed_minutes"] = elapsed
    details["expected_volume_by_time"] = expected_volume
    details["volume_ratio"] = volume_ratio
    if volume_ratio < volume_spike_multiplier:
        return RiskDecision(False, "开盘暴跌但未放量", details)

    return RiskDecision(
        True,
        f"单票暴跌禁买：{code} 开盘跌幅 {open_drop_pct:.2f}% 且放量 {volume_ratio:.1f}x 砸穿支撑 {support:.2f}",
        {**details, "trigger": "opening_crash"},
    )


def evaluate_buy_risk_guard(
    *,
    code: str,
    tick: Any,
    prev_close: float | None = None,
    support_level: float | None = None,
    avg_vol_5d: float | None = None,
    market_fetcher: Callable[[], RiskDecision] | None = None,
) -> RiskDecision:
    """统一买入前置风控：先大盘熔断，再单票暴跌过滤。"""
    market = get_market_panic_decision(market_fetcher)
    if market.blocked:
        return market

    crash = evaluate_opening_crash_filter(
        code=code,
        current_price=getattr(tick, "last_price", 0.0),
        open_price=getattr(tick, "open_price", 0.0),
        prev_close=prev_close or getattr(tick, "pre_close", 0.0),
        low_price=getattr(tick, "low_price", None),
        support_level=support_level,
        current_volume=getattr(tick, "volume", None),
        avg_vol_5d=avg_vol_5d,
    )
    if crash.blocked:
        return crash

    return RiskDecision(
        False,
        "买入风控通过",
        {"market": market.details, "opening_crash": crash.details},
    )
