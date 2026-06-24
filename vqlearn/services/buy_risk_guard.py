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
import sqlite3


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
    # 当 fetcher 是外部传入的（非默认 fetch_market_panic_snapshot），跳过缓存
    fetcher = fetcher or fetch_market_panic_snapshot
    is_default_fetcher = (fetcher is fetch_market_panic_snapshot)
    if _MARKET_CACHE is not None and is_default_fetcher:
        ts, cached = _MARKET_CACHE
        if (now - ts).total_seconds() < _MARKET_CACHE_SECONDS:
            return cached
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
    db_path: str | None = None,
    account_id: int = 1,
    prev_close: float | None = None,
    support_level: float | None = None,
    avg_vol_5d: float | None = None,
    market_fetcher: Callable[[], RiskDecision] | None = None,
    max_positions: int = 6,
    max_daily_new: int = 2,
) -> RiskDecision:
    """统一买入前置风控：大盘熔断 + 单票暴跌 + 持仓数量上限(REQ-038) + 单日新建仓位上限(REQ-038)。
    
    当 db_path 提供时，额外执行 REQ-038 的两个硬性风控检查。
    """
    # 1. 大盘熔断
    market = get_market_panic_decision(market_fetcher)
    if market.blocked:
        return market

    # 2. 单票开盘暴跌
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

    # 3. REQ-038: 持仓数量上限 + 单日新建仓位数上限
    if db_path:
        # 3a. 总持仓数量上限
        pos_count = check_position_count_limit(
            db_path=db_path,
            account_id=account_id,
            max_positions=max_positions,
        )
        if pos_count.blocked:
            return pos_count

        # 3b. 单日新建仓位数上限（仅新建仓，加仓不受限）
        from datetime import date
        today = date.today().strftime("%Y-%m-%d")
        new_pos = check_daily_new_position_limit(
            db_path=db_path,
            account_id=account_id,
            trade_date=today,
            max_daily_new=max_daily_new,
            code=code,
        )
        # 判断是否是加仓（已有持仓则不受新建仓位上限约束）
        is_add = False
        try:
            import sqlite3 as _sq
            _c = _sq.connect(db_path)
            _r = _c.execute(
                "SELECT quantity FROM sim_positions WHERE account_id = ? AND stock_code = ? AND quantity > 0",
                (account_id, code)
            ).fetchone()
            is_add = _r is not None and int(_r[0]) > 0
            _c.close()
        except Exception:
            pass
        if new_pos.blocked and not is_add:
            return new_pos

        return RiskDecision(
            False,
            "买入风控全部通过（大盘+单票暴跌+持仓数+新建仓位）",
            {
                "market": market.details,
                "opening_crash": crash.details,
                "position_count": pos_count.details,
                "daily_new_position": new_pos.details,
            },
        )

    # db_path 未提供时，只做大盘+单票检查（向后兼容）
    return RiskDecision(
        False,
        "买入风控通过（大盘+单票暴跌）",
        {"market": market.details, "opening_crash": crash.details},
    )


def check_position_limit(
    *,
    db_path: str,
    account_id: int = 1,
    code: str,
    max_position_pct: float = 0.20,
    current_price: float = 0.0,
    additional_shares: int = 100,
) -> RiskDecision:
    """检查持仓数量上限：买入后该股票市值占比是否超过 max_position_pct。

    参数：
    - db_path: sim.db 路径
    - account_id: 账户 ID
    - code: 股票代码
    - max_position_pct: 单票最大仓位比例（0-1）
    - current_price: 当前股价
    - additional_shares: 计划买入股数（100 的整数倍）

    返回 RiskDecision：
    - blocked=True 表示超过仓位上限，禁止买入
    - blocked=False 表示通过检查
    """
    details = {
        "code": code,
        "account_id": account_id,
        "max_position_pct": max_position_pct,
        "current_price": current_price,
        "additional_shares": additional_shares,
    }

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 获取账户总资产
        cursor.execute(
            "SELECT total_value FROM sim_account WHERE id = ? ORDER BY id DESC LIMIT 1",
            (account_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return RiskDecision(False, "无法获取账户资产，跳过仓位检查", {**details, "error": "account_not_found"})
        total_assets = float(row[0])
        details["total_assets"] = total_assets

        # 获取当前持仓（含成本和数量）
        cursor.execute(
            "SELECT quantity, avg_cost FROM sim_positions WHERE account_id = ? AND stock_code = ? AND quantity > 0",
            (account_id, code)
        )
        pos_row = cursor.fetchone()
        current_volume = int(pos_row[0]) if pos_row else 0
        current_cost = float(pos_row[1]) if pos_row else 0.0
        details["current_volume"] = current_volume
        details["current_cost"] = current_cost

        # 计算买入后该股票的市值占比
        new_volume = current_volume + additional_shares
        new_market_value = new_volume * current_price
        position_pct = new_market_value / max(total_assets, 1.0)
        details["new_volume"] = new_volume
        details["new_market_value"] = new_market_value
        details["position_pct"] = position_pct

        conn.close()

        if position_pct > max_position_pct:
            return RiskDecision(
                True,
                f"持仓超限：{code} 买入后仓位 {position_pct:.2%} > 上限 {max_position_pct:.2%}",
                {**details, "trigger": "position_limit"},
            )

        return RiskDecision(
            False,
            f"仓位检查通过：{code} 买入后仓位 {position_pct:.2%} <= 上限 {max_position_pct:.2%}",
            details,
        )

    except Exception as exc:
        return RiskDecision(False, f"仓位检查异常：{exc}", {**details, "error": str(exc)})


def check_daily_trade_limit(
    *,
    db_path: str,
    account_id: int = 1,
    trade_date: str | None = None,
    max_daily_trades: int = 10,
) -> RiskDecision:
    """检查单日交易笔数上限（所有买入笔数）。"""
    from datetime import date

    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    details = {
        "account_id": account_id,
        "trade_date": trade_date,
        "max_daily_trades": max_daily_trades,
    }

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute(
            """SELECT COUNT(*) FROM sim_trades 
            WHERE account_id = ? AND direction = 'BUY' AND trade_date LIKE ?""",
            (account_id, f"{trade_date}%")
        )
        row = cursor.fetchone()
        daily_trades = int(row[0]) if row else 0
        details["daily_trades"] = daily_trades

        conn.close()

        if daily_trades >= max_daily_trades:
            return RiskDecision(
                True,
                f"单日交易超限：今日已买入 {daily_trades} 笔 >= 上限 {max_daily_trades} 笔",
                {**details, "trigger": "daily_trade_limit"},
            )

        return RiskDecision(
            False,
            f"单日交易检查通过：今日已买入 {daily_trades} 笔 < 上限 {max_daily_trades} 笔",
            details,
        )

    except Exception as exc:
        return RiskDecision(False, f"单日交易检查异常：{exc}", {**details, "error": str(exc)})


def check_position_count_limit(
    *,
    db_path: str,
    account_id: int = 1,
    max_positions: int = 6,
) -> RiskDecision:
    """检查总持仓股票数量上限（默认 ≤6，可配置）。

    参数：
    - db_path: 数据库路径（sim.db 或 sim_live_mirror.db）
    - account_id: 账户 ID
    - max_positions: 最大持仓股票数（默认 6）

    返回 RiskDecision：
    - blocked=True 表示持仓数量已达上限，禁止新建仓位
    - blocked=False 表示通过检查
    """
    details = {
        "account_id": account_id,
        "max_positions": max_positions,
    }

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 统计当前持仓股票数量（quantity > 0）
        cursor.execute(
            "SELECT COUNT(*) FROM sim_positions WHERE account_id = ? AND quantity > 0",
            (account_id,)
        )
        row = cursor.fetchone()
        current_positions = int(row[0]) if row else 0
        details["current_positions"] = current_positions

        conn.close()

        if current_positions >= max_positions:
            return RiskDecision(
                True,
                f"持仓数量超限：当前持有 {current_positions} 只股票 >= 上限 {max_positions} 只",
                {**details, "trigger": "position_count_limit"},
            )

        return RiskDecision(
            False,
            f"持仓数量检查通过：当前持有 {current_positions} 只股票 < 上限 {max_positions} 只",
            details,
        )

    except Exception as exc:
        return RiskDecision(False, f"持仓数量检查异常：{exc}", {**details, "error": str(exc)})


def check_daily_new_position_limit(
    *,
    db_path: str,
    account_id: int = 1,
    trade_date: str | None = None,
    max_daily_new: int = 2,
    code: str | None = None,
) -> RiskDecision:
    """检查单日新建仓位数上限（默认 ≤2，可配置）。

    「新建仓位」定义：当日买入某股票时，该股票在买入前无任何持仓（quantity=0）。
    加仓（已有持仓后再买）不计入新建仓位上限。

    参数：
    - db_path: 数据库路径
    - account_id: 账户 ID
    - trade_date: 交易日期（YYYY-MM-DD），默认今天
    - max_daily_new: 每日最大新建仓位数（默认 2）
    - code: 当前正要买入的股票代码（可选；若提供则在检查同时通过返回
            决定是否允许这只新股建仓）

    返回 RiskDecision：
    - blocked=True 表示当日新建仓位已达上限
    - blocked=False 表示通过检查
    """
    from datetime import date

    if trade_date is None:
        trade_date = date.today().strftime("%Y-%m-%d")

    details = {
        "account_id": account_id,
        "trade_date": trade_date,
        "max_daily_new": max_daily_new,
        "code": code,
    }

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 获取当日所有买入交易
        cursor.execute(
            """SELECT stock_code FROM sim_trades
            WHERE account_id = ? AND direction = 'BUY' AND trade_date LIKE ?""",
            (account_id, f"{trade_date}%")
        )
        bought_codes = [row[0] for row in cursor.fetchall()]
        details["bought_codes_today"] = bought_codes

        # 对于每只当日买入的股票，判断买入时是否为「新建仓位」
        # 方法：检查该股票在当日第一笔买入前是否有持仓
        # 简化实现：若当前 positions.quantity = 0，或者当日第一笔买入前无持仓记录
        # 这里用「当前无持仓 或 该股票从未在 trades 里出现过」来近似
        # 更精确的做法是用 sim_positions 历史快照，但当前 db 无快照表，
        # 用「当日之前该股票无任何买入记录」作为「新建仓位」的判断依据
        cursor.execute(
            """SELECT DISTINCT stock_code FROM sim_trades
            WHERE account_id = ? AND direction = 'BUY' AND trade_date < ?""",
            (account_id, trade_date)
        )
        ever_bought_codes = set(row[0] for row in cursor.fetchall())
        details["ever_bought_codes"] = list(ever_bought_codes)

        # 当日买入的股票中，哪些是「新建仓位」（之前从未买过）
        new_positions_today = [c for c in bought_codes if c not in ever_bought_codes]
        # 去重（同一股票可能买了多次，但只算一次新建）
        new_positions_today = list(dict.fromkeys(new_positions_today))
        details["new_positions_today"] = new_positions_today
        details["new_positions_count"] = len(new_positions_today)

        conn.close()

        # 如果当前要买入的 code 之前从未买过，且今天还没建过这只，算入新建
        if code and code not in ever_bought_codes and code not in new_positions_today:
            # 这只新股还没计入，需要占用一个名额
            projected_count = len(new_positions_today) + 1
        else:
            projected_count = len(new_positions_today)
        details["projected_new_positions"] = projected_count

        if projected_count > max_daily_new:
            return RiskDecision(
                True,
                f"单日新建仓位超限：今日已新建 {len(new_positions_today)} 只 >= 上限 {max_daily_new} 只（含当前将建的 {code}）",
                {**details, "trigger": "daily_new_position_limit"},
            )

        return RiskDecision(
            False,
            f"单日新建仓位检查通过：今日已新建 {len(new_positions_today)} 只 < 上限 {max_daily_new} 只",
            details,
        )

    except Exception as exc:
        return RiskDecision(False, f"单日新建仓位检查异常：{exc}", {**details, "error": str(exc)})


def evaluate_buy_risk_with_limits(
    *,
    code: str,
    tick: Any,
    db_path: str,
    account_id: int = 1,
    prev_close: float | None = None,
    support_level: float | None = None,
    avg_vol_5d: float | None = None,
    market_fetcher: Callable[[], RiskDecision] | None = None,
    max_position_pct: float = 0.20,
    max_daily_trades: int = 10,
    max_positions: int = 6,
    max_daily_new: int = 2,
    additional_shares: int = 100,
) -> RiskDecision:
    """统一买入风控：大盘熔断 + 单票暴跌 + 持仓数量上限 + 单日新建仓位上限 + 单票仓位上限 + 单日交易上限。"""
    # 1. 大盘熔断
    market = get_market_panic_decision(market_fetcher)
    if market.blocked:
        return market

    # 2. 单票开盘暴跌
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

    # 3. 总持仓数量上限（REQ-038）
    pos_count = check_position_count_limit(
        db_path=db_path,
        account_id=account_id,
        max_positions=max_positions,
    )
    if pos_count.blocked:
        return pos_count

    # 4. 单日新建仓位数上限（REQ-038）
    # 仅当该股票当前无持仓时才受新建仓位上限约束
    # 加仓（已有持仓再买）不受此限
    from datetime import date
    today = date.today().strftime("%Y-%m-%d")
    new_pos_check = check_daily_new_position_limit(
        db_path=db_path,
        account_id=account_id,
        trade_date=today,
        max_daily_new=max_daily_new,
        code=code,
    )
    # 判断是否是加仓：当前已有持仓则不阻断（新建仓位上限只限「新票」）
    is_add_position = False
    try:
        import sqlite3 as _sqlite3
        _conn = _sqlite3.connect(db_path)
        _row = _conn.execute(
            "SELECT quantity FROM sim_positions WHERE account_id = ? AND stock_code = ? AND quantity > 0",
            (account_id, code)
        ).fetchone()
        is_add_position = _row is not None and int(_row[0]) > 0
        _conn.close()
    except Exception:
        pass
    if new_pos_check.blocked and not is_add_position:
        return new_pos_check

    # 5. 单票仓位上限（原有逻辑）
    current_price = getattr(tick, "last_price", 0.0)
    position_check = check_position_limit(
        db_path=db_path,
        account_id=account_id,
        code=code,
        max_position_pct=max_position_pct,
        current_price=current_price,
        additional_shares=additional_shares,
    )
    if position_check.blocked:
        return position_check

    # 6. 单日交易笔数上限（原有逻辑）
    daily_check = check_daily_trade_limit(
        db_path=db_path,
        account_id=account_id,
        max_daily_trades=max_daily_trades,
    )
    if daily_check.blocked:
        return daily_check

    return RiskDecision(
        False,
        "买入风控全部通过（大盘+单票+持仓数+新建仓位+单票仓位+单日交易）",
        {
            "market": market.details,
            "opening_crash": crash.details,
            "position_count": pos_count.details,
            "daily_new_position": new_pos_check.details,
            "position_limit": position_check.details,
            "daily_trade_limit": daily_check.details,
        },
    )
