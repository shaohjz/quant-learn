#!/usr/bin/env python3
"""自动补数据脚本 - 从最后日期补到最新交易日
数据源：BaoStock 主力 + AKShare 备选（带退避重试）
"""

import os
import sys
import time
import random
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

DATA_DIR = Path("data")
LOG_FILE = Path("output/backfill.log")

LOG_FILE.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# BaoStock 全局连接
_bs_connected = False

def _bs_ensure_login():
    global _bs_connected
    if not _bs_connected:
        import baostock as bs
        rs = bs.login()
        if rs.error_code != '0':
            raise RuntimeError(f"BaoStock login failed: {rs.error_msg}")
        _bs_connected = True

def fetch_from_baostock(symbol: str, start_date: str, end_date: str,
                         max_retries: int = 3) -> Optional[pd.DataFrame]:
    """从 BaoStock 获取日K线（复用全局连接）"""
    import baostock as bs

    prefix = "sh" if symbol.startswith("6") else "sz"
    bs_code = f"{prefix}.{symbol}"

    try:
        _bs_ensure_login()
    except RuntimeError as e:
        log.warning(f"  [BaoStock] 登录失败: {e}")
        return None

    for attempt in range(1, max_retries + 1):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",
            )
            if rs.error_code != '0':
                log.warning(f"  [BaoStock] {symbol} 查询失败(尝试{attempt}): {rs.error_msg}")
                time.sleep(2 * attempt)
                continue

            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                log.debug(f"  [BaoStock] {symbol} 无数据（{start_date}~{end_date}）")
                return None

            df = pd.DataFrame(data_list, columns=["date", "open", "high", "low", "close", "volume"])
            df["date"] = pd.to_datetime(df["date"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(float)
            df = df.dropna(subset=["open", "close"])
            df = df.sort_values("date").reset_index(drop=True)

            log.debug(f"  [BaoStock] {symbol} 获取 {len(df)} 条")
            return df

        except Exception as e:
            log.warning(f"  [BaoStock] {symbol} 异常(尝试{attempt}): {e}")
            if attempt < max_retries:
                sleep_sec = 2 ** attempt + random.uniform(0, 1)
                time.sleep(sleep_sec)
            else:
                return None

    return None


def fetch_from_akshare(symbol: str, start_date: str, end_date: str,
                        max_retries: int = 2) -> Optional[pd.DataFrame]:
    """从 AKShare 获取日K线（BaoStock 失败时的备选）
    
    AKShare 在东财接口限流时会被封禁，因此快速失败（max_retries=2，总耗时 < 5s）
    """
    try:
        import akshare as ak
    except ImportError:
        log.debug(f"  [AKShare] {symbol} akshare 未安装")
        return None

    # 如果 end_date 是今天且是交易日收盘前，跳过 AKShare（今天数据肯定还没有）
    today_str = datetime.now().strftime('%Y-%m-%d')
    if end_date >= today_str:
        log.debug(f"  [AKShare] {symbol} 跳过（end_date={end_date} 是今天或未来）")
        return None

    for attempt in range(1, max_retries + 1):
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust="qfq",  # 前复权
            )
            if df is not None and not df.empty:
                # 统一列名
                col_map = {
                    "日期": "date", "开盘": "open", "最高": "high",
                    "最低": "low", "收盘": "close", "成交量": "volume",
                }
                df = df.rename(columns=col_map)
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(float)
                df = df.dropna(subset=["open", "close"]).sort_values("date").reset_index(drop=True)
                log.debug(f"  [AKShare] {symbol} 获取 {len(df)} 条")
                return df
            return None
        except Exception as e:
            log.warning(f"  [AKShare] {symbol} 异常(尝试{attempt}): {e}")
            if attempt < max_retries:
                sleep_sec = 1.0 * attempt  # 快速退避：1s, 2s
                time.sleep(sleep_sec)
            else:
                return None
    return None


def fetch_stock_data(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """获取单只股票数据：BaoStock 主力，AKShare 备选，本地缓存兜底"""
    df = fetch_from_baostock(symbol, start_date, end_date)
    if df is not None and not df.empty:
        log.info(f"  ✓ {symbol} [BaoStock] {len(df)} 条")
        return df
    log.warning(f"  ✗ {symbol} BaoStock 失败，尝试 AKShare...")
    df = fetch_from_akshare(symbol, start_date, end_date)
    if df is not None and not df.empty:
        log.info(f"  ✓ {symbol} [AKShare] {len(df)} 条")
        return df
    # 在线数据源全部失败，尝试本地 CSV 缓存兜底
    log.warning(f"  ⚠️ {symbol} 所有在线数据源失败，尝试本地缓存兜底...")
    try:
        cached = _fetch_from_local_cache(symbol, start_date, end_date)
        if cached is not None and not cached.empty:
            log.info(f"  ✓ {symbol} [本地缓存] {len(cached)} 条（最后日期: {cached['date'].max()}）")
            return cached
    except Exception as e:
        log.warning(f"  ✗ {symbol} 本地缓存也失败: {e}")
    log.warning(f"  ✗✗ {symbol} 所有来源均无数据（{start_date}~{end_date}）")
    return None


def _fetch_from_local_cache(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """从本地 data/*.csv 读取缓存数据兜底"""
    csv_path = Path(__file__).resolve().parent.parent / 'data' / f"{symbol}.csv"
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    if 'date' not in df.columns or df.empty:
        return None
    df['date'] = pd.to_datetime(df['date'])
    sd = pd.to_datetime(start_date)
    ed = pd.to_datetime(end_date)
    mask = (df['date'] >= sd) & (df['date'] <= ed)
    result = df[mask].copy()
    if result.empty:
        # 返回全部本地数据（调用方自行处理）
        log.warning(f"  [缓存] {symbol} 无 {start_date}~{end_date} 数据，返回全部 {len(df)} 行")
        return df.sort_values('date').reset_index(drop=True)
    return result.sort_values('date').reset_index(drop=True)


def get_last_date(csv_file: Path) -> Optional[str]:
    try:
        df = pd.read_csv(csv_file)
        if df.empty or 'date' not in df.columns:
            return None
        last_date = str(df['date'].iloc[-1])
        return last_date
    except Exception as e:
        log.error(f"  读取最后日期失败 {csv_file.name}: {e}")
        return None


def backfill_stock(symbol: str, csv_file: Path) -> bool:
    """补单只股票的数据"""
    last_date = get_last_date(csv_file)
    if last_date is None:
        log.warning(f"  {symbol}: 无法读取最后日期，跳过")
        return False

    last_dt = datetime.strptime(last_date, '%Y-%m-%d')
    next_dt = last_dt + timedelta(days=1)
    today = datetime.now().date()

    if next_dt.date() > today:
        log.info(f"  {symbol}: 数据已是最新 ({last_date})")
        return True

    start_str = next_dt.strftime('%Y-%m-%d')
    end_str = today.strftime('%Y-%m-%d')

    # 如果 end_str 是今天且当前时间早于 15:30（收盘后数据才可用），则截止到昨天
    now = datetime.now()
    if end_str == now.strftime('%Y-%m-%d') and now.hour < 15:
        end_adjusted = (now - timedelta(days=1)).strftime('%Y-%m-%d')
        if end_adjusted >= start_str:
            end_str = end_adjusted
            log.debug(f"  {symbol}: 今天数据未更新，截止到 {end_str}")
        else:
            log.info(f"  {symbol}: 数据已是最新（昨天已补）（{last_date}）")
            return True

    log.info(f"  {symbol}: 补数据 {start_str} ~ {end_str}")
    df_new = fetch_stock_data(symbol, start_str, end_str)
    if df_new is None or df_new.empty:
        log.info(f"  {symbol}: 无新数据（可能非交易日）")
        return True

    df_old = pd.read_csv(csv_file)
    df_old["date"] = pd.to_datetime(df_old["date"])
    df_new["date"] = pd.to_datetime(df_new["date"])
    df_combined = pd.concat([df_old, df_new], ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset=['date'], keep='last')
    df_combined = df_combined.sort_values('date').reset_index(drop=True)
    df_combined.to_csv(csv_file, index=False)

    log.info(f"  ✓ {symbol}: 补了 {len(df_new)} 条，现共 {len(df_combined)} 条")
    return True


def main():
    print("=" * 60)
    print(f"自动补数据 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("数据源: BaoStock 主力 + AKShare 备选（带退避重试）")
    print("=" * 60)

    csv_files = sorted([f for f in DATA_DIR.glob("*.csv") if f.stem.isdigit()])
    print(f"找到 {len(csv_files)} 个股票文件\n")
    log.info(f"开始补数据，共 {len(csv_files)} 只股票")

    # 全局登录一次
    try:
        _bs_ensure_login()
        log.info("BaoStock 全局登录成功")
    except RuntimeError as e:
        log.error(f"BaoStock 登录失败: {e}")
        return

    success = 0
    failed = 0

    for i, csv_file in enumerate(csv_files):
        symbol = csv_file.stem
        print(f"📈 {symbol} ({i+1}/{len(csv_files)}):")
        try:
            ok = backfill_stock(symbol, csv_file)
            if ok:
                success += 1
            else:
                failed += 1
        except Exception as e:
            log.error(f"  ❌ {symbol}: 错误: {e}")
            failed += 1

        delay = random.uniform(0.3, 0.8)
        time.sleep(delay)

    # 登出
    try:
        import baostock as bs
        bs.logout()
    except Exception:
        pass

    print(f"\n{'=' * 60}")
    print(f"完成: 成功 {success}, 失败 {failed}")
    print(f"日志: {LOG_FILE}")
    print(f"{'=' * 60}")
    log.info(f"补数据完成: 成功={success}, 失败={failed}")


if __name__ == "__main__":
    main()
