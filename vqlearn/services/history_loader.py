"""
vqlearn/services/history_loader.py

历史 K 线数据加载（带本地缓存）。
- baostock 拉日 K（不复权 / 后复权）
- 缓存到 data/cache/history/{code}_{adjust}_{start}_{end}.csv
- 7 天内的缓存直接复用，避免重复拉数据
"""
from __future__ import annotations
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / 'data' / 'cache' / 'history'
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _exchange_prefix(code: str) -> str:
    """返回 baostock 的市场前缀"""
    if code.startswith(('60', '68', '90')):
        return 'sh'
    if code.startswith(('00', '30')):
        return 'sz'
    if code.startswith(('8', '4')):
        return 'bj'
    return 'sh'


def load_history(
    code: str,
    start: str = '2024-01-01',
    end: str | None = None,
    adjust: str = '3',  # '1'=后复权 '2'=前复权 '3'=不复权
    use_cache: bool = True,
    cache_max_age_days: int = 7,
) -> pd.DataFrame:
    """
    返回 DataFrame: columns=[date, open, high, low, close, volume, amount, turnover]
    """
    if end is None:
        end = datetime.now().strftime('%Y-%m-%d')

    cache_file = CACHE_DIR / f"{code}_{adjust}_{start}_{end}.csv"

    # 缓存命中
    if use_cache and cache_file.exists():
        age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
        if age.days < cache_max_age_days:
            try:
                df = pd.read_csv(cache_file)
                if not df.empty:
                    return df
            except Exception:
                pass

    # baostock 拉
    import baostock as bs
    bs.login()
    try:
        full_code = f"{_exchange_prefix(code)}.{code}"
        rs = bs.query_history_k_data_plus(
            full_code,
            "date,open,high,low,close,volume,amount,turn,pctChg",
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag=adjust,
        )
        rows = []
        while rs.error_code == '0' and rs.next():
            rows.append(rs.get_row_data())
    finally:
        bs.logout()

    if not rows:
        return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover', 'pct'])

    df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover', 'pct'])
    for col in ['open', 'high', 'low', 'close', 'amount', 'turnover', 'pct']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce').astype('Int64')
    df = df.dropna(subset=['close'])

    # 写缓存
    try:
        df.to_csv(cache_file, index=False)
    except Exception:
        pass

    return df


def load_history_batch(codes: list[str], start: str, end: str | None = None, adjust: str = '3') -> dict[str, pd.DataFrame]:
    """批量拉取多只股票"""
    result = {}
    for code in codes:
        result[code] = load_history(code, start, end, adjust)
    return result
