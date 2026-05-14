"""
sim/trade_calendar.py
A股交易日历 — 用 akshare 拉新浪官方交易日，本地缓存到 data/trade_dates.json。

策略：
  - 第一次调用拉全量并缓存
  - 缓存超过 7 天自动刷新（节假日提前公告，足够时效）
  - 网络失败时回退到"周末判定"
"""

import json
from datetime import date as Date, datetime, timedelta
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CACHE_FILE = _PROJECT_ROOT / "data" / "trade_dates.json"
_CACHE_TTL_DAYS = 7

_cache = None  # 内存缓存：set[str]


def _refresh_cache():
    """从 akshare 拉交易日并写本地缓存"""
    global _cache
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        dates = sorted({str(d) for d in df["trade_date"].tolist()})
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "updated_at": datetime.now().isoformat(),
                "dates": dates,
            }, f, ensure_ascii=False)
        _cache = set(dates)
        return True
    except Exception as e:
        print(f"⚠ 拉取交易日历失败：{e}（回退到本地缓存或周末判定）")
        return False


def _load_cache() -> set:
    """从本地缓存加载，过期则刷新；都失败返回 None"""
    global _cache
    if _cache is not None:
        return _cache

    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            updated = datetime.fromisoformat(data["updated_at"])
            if datetime.now() - updated < timedelta(days=_CACHE_TTL_DAYS):
                _cache = set(data["dates"])
                return _cache
        except Exception:
            pass

    # 缓存不存在或过期，尝试刷新
    if _refresh_cache():
        return _cache

    # 刷新失败，但若有旧缓存也凑合用
    if _CACHE_FILE.exists():
        try:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = set(json.load(f)["dates"])
                return _cache
        except Exception:
            pass

    return None


def is_trading_day(d: Date = None) -> bool:
    """是否为交易日"""
    d = d or Date.today()
    cache = _load_cache()
    if cache:
        return d.strftime("%Y-%m-%d") in cache
    # 兜底：周末判定
    return d.weekday() < 5


def next_trading_day(d: Date = None, max_days: int = 14) -> Date:
    """下一个交易日"""
    d = d or Date.today()
    cur = d + timedelta(days=1)
    for _ in range(max_days):
        if is_trading_day(cur):
            return cur
        cur += timedelta(days=1)
    return cur


def prev_trading_day(d: Date = None, max_days: int = 14) -> Date:
    """上一个交易日"""
    d = d or Date.today()
    cur = d - timedelta(days=1)
    for _ in range(max_days):
        if is_trading_day(cur):
            return cur
        cur -= timedelta(days=1)
    return cur


def force_refresh():
    """手动强制刷新"""
    global _cache
    _cache = None
    return _refresh_cache()


if __name__ == "__main__":
    today = Date.today()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    print(f"今天 {today} ({weekdays[today.weekday()]}) 交易日: {is_trading_day(today)}")
    print(f"上一交易日: {prev_trading_day(today)}")
    print(f"下一交易日: {next_trading_day(today)}")
