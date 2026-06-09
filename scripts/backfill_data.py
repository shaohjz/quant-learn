#!/usr/bin/env python3
"""自动补数据脚本 - 从最后日期补到最新交易日
支持 BaoStock（主力）+ AKShare（备选）双数据源，带指数退避重试
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

# 配置日志
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


# ──────────────────────────────────────────────
# BaoStock 数据源（主力）
# ──────────────────────────────────────────────

def _bs_login():
    import baostock as bs
    rs = bs.login()
    if rs.error_code != '0':
        raise RuntimeError(f"BaoStock login failed: {rs.error_msg}")
    return bs


def fetch_from_baostock(symbol: str, start_date: str, end_date: str,
                         max_retries: int = 3) -> Optional[pd.DataFrame]:
    """从 BaoStock 获取日K线，带重试"""
    import baostock as bs

    # 转换 symbol 格式：600519 -> sh.600519, 000333 -> sz.000333
    if symbol.startswith('6'):
        bs_code = f"sh.{symbol}"
    else:
        bs_code = f"sz.{symbol}"

    for attempt in range(1, max_retries + 1):
        try:
            _bs_login()  # 每次请求前确保登录（logout 在 finally 中）

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,volume",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",  # 前复权
            )
            if rs.error_code != '0':
                log.warning(f"  [BaoStock] {symbol} 查询失败(尝试{attempt}): {rs.error_msg}")
                time.sleep(2 * attempt)
                continue

            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            bs.logout()

            if not data_list:
                log.debug(f"  [BaoStock] {symbol} 无数据（{start_date}~{end_date}）")
                return None

            df = pd.DataFrame(data_list, columns=["date", "code", "open", "high", "low", "close", "volume"])
            df = df.rename(columns={"code": "_bs_code"})
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
            try:
                bs.logout()
            except Exception:
                pass
            if attempt < max_retries:
                sleep_sec = 2 ** attempt + random.uniform(0, 1)
                time.sleep(sleep_sec)
            else:
                return None

    return None


# ──────────────────────────────────────────────
# AKShare 数据源（备选）
# ──────────────────────────────────────────────

def fetch_from_akshare(symbol: str, start_date: str, end_date: str,
                       max_retries: int = 3) -> Optional[pd.DataFrame]:
    """从 AKShare 获取日K线，带指数退避重试"""
    try:
        import akshare as ak
    except ImportError:
        log.warning("  [AKShare] akshare 未安装，跳过")
        return None

    start_fmt = start_date.replace('-', '')
    end_fmt = end_date.replace('-', '')

    for attempt in range(1, max_retries + 1):
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_fmt,
                end_date=end_fmt,
                adjust="qfq",
            )
            if df is None or df.empty:
                log.debug(f"  [AKShare] {symbol} 无数据")
                return None

            # 统一列名
            col_map = {
                "日期": "date", "开盘": "open", "最高": "high",
                "最低": "low", "收盘": "close", "成交量": "volume",
            }
            available = [c for c in col_map if c in df.columns]
            if available:
                df = df[available].rename(columns=col_map)
            else:
                # 已经是英文列名
                df = df[["date", "open", "high", "low", "close", "volume"]]

            df["date"] = pd.to_datetime(df["date"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(float)
            df = df.dropna(subset=["open", "close"])
            df = df.sort_values("date").reset_index(drop=True)

            log.debug(f"  [AKShare] {symbol} 获取 {len(df)} 条")
            return df

        except Exception as e:
            log.warning(f"  [AKShare] {symbol} 异常(尝试{attempt}): {e}")
            if attempt < max_retries:
                sleep_sec = 2 ** attempt + random.uniform(0, 2)
                time.sleep(sleep_sec)
            else:
                return None

    return None


# ──────────────────────────────────────────────
# 统一获取接口（BaoStock 优先，AKShare 备选）
# ──────────────────────────────────────────────

def fetch_stock_data(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """获取单只股票数据，BaoStock 优先，失败后用 AKShare"""
    # 1. 先试 BaoStock（主力数据源）
    df = fetch_from_baostock(symbol, start_date, end_date)
    if df is not None and not df.empty:
        log.info(f"  ✓ {symbol} [BaoStock] {len(df)} 条")
        return df

    # 2. BaoStock 失败，试 AKShare
    log.info(f"  ↩ {symbol} BaoStock 无数据，尝试 AKShare...")
    df = fetch_from_akshare(symbol, start_date, end_date)
    if df is not None and not df.empty:
        log.info(f"  ✓ {symbol} [AKShare] {len(df)} 条")
        return df

    log.warning(f"  ✗ {symbol} 所有数据源均无数据（{start_date}~{end_date}）")
    return None


# ──────────────────────────────────────────────
# 核心逻辑
# ──────────────────────────────────────────────

def get_last_date(csv_file: Path) -> Optional[str]:
    """获取 CSV 文件的最后日期"""
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
    """补单只股票的数据，返回是否成功"""
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
    log.info(f"  {symbol}: 补数据 {start_str} ~ {end_str}")

    df_new = fetch_stock_data(symbol, start_str, end_str)
    if df_new is None or df_new.empty:
        log.info(f"  {symbol}: 无新数据（可能非交易日）")
        return True  # 非交易日不是错误

    # 合并到原文件
    df_old = pd.read_csv(csv_file)
    # 统一 date 列类型，避免 Timestamp vs str 比较错误
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
    print("=" * 60)

    csv_files = sorted([f for f in DATA_DIR.glob("*.csv") if f.stem.isdigit()])
    print(f"找到 {len(csv_files)} 个股票文件\n")
    log.info(f"开始补数据，共 {len(csv_files)} 只股票")

    success = 0
    failed = 0
    skipped = 0

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

        # 每只股票之间随机延迟，避免被限流
        delay = random.uniform(0.5, 1.5)
        time.sleep(delay)

    print(f"\n{'=' * 60}")
    print(f"完成: 成功 {success}, 失败 {failed}, 跳过 {skipped}")
    print(f"日志: {LOG_FILE}")
    print(f"{'=' * 60}")
    log.info(f"补数据完成: 成功={success}, 失败={failed}")


if __name__ == "__main__":
    main()
