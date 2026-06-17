#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量抓取所有股票的日线数据（优化版）
- 主力数据源：BaoStock（稳定可靠）
- AKShare 已永久移除（连续 7 天不可用，2026-06-16）
- 优化：跳过已有今日数据的股票，并行请求，减少延迟
"""

import os
import sys
import time
import random
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

DATA_DIR = Path("data")


# BaoStock 全局连接（复用，避免每次 login/logout）
_bs_connected = False

def _bs_ensure_login():
    """确保 BaoStock 已登录（全局复用）"""
    global _bs_connected
    if not _bs_connected:
        import baostock as bs
        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"BaoStock login failed: {lg.error_msg}")
        _bs_connected = True


def fetch_from_baostock(symbol: str, start_date: str, end_date: str) -> pd.DataFrame | None:
    """从 BaoStock 获取日K线（复用全局连接）"""
    import baostock as bs

    prefix = "sh" if symbol.startswith("6") else "sz"
    bs_code = f"{prefix}.{symbol}"

    try:
        _bs_ensure_login()
    except RuntimeError as e:
        log.warning(f"  [BaoStock] 登录失败: {e}")
        return None

    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",  # 前复权
        )
        if rs.error_code != "0":
            log.warning(f"  [BaoStock] {symbol} 查询失败: {rs.error_msg}")
            return None

        data_list = []
        while rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            return None

        df = pd.DataFrame(data_list, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(float)
        df = df.dropna(subset=["open", "close"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception as e:
        log.warning(f"  [BaoStock] {symbol} 查询异常: {e}")
        return None


def has_today_data(symbol: str) -> bool:
    """检查 CSV 文件是否已有今日数据"""
    filepath = DATA_DIR / f"{symbol}.csv"
    if not filepath.exists():
        return False
    try:
        df = pd.read_csv(filepath)
        if df.empty or "date" not in df.columns:
            return False
        today_str = datetime.now().strftime("%Y-%m-%d")
        # 统一日期格式
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        return today_str in df["date"].values
    except Exception:
        return False


def update_stock(symbol: str) -> tuple[str, str]:
    """更新单只股票数据，返回 (symbol, status)"""
    # 检查是否已有今日数据
    if has_today_data(symbol):
        return symbol, "skipped"

    filepath = DATA_DIR / f"{symbol}.csv"

    # 获取现有数据的最后日期
    last_date = None
    if filepath.exists():
        try:
            df_existing = pd.read_csv(filepath)
            if not df_existing.empty and "date" in df_existing.columns:
                last_date = str(pd.to_datetime(df_existing["date"].iloc[-1]).date())
        except Exception:
            pass

    if last_date:
        start_date = last_date
    else:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    end_date = datetime.now().strftime("%Y-%m-%d")

    log.info(f"  {symbol}: 获取 {start_date} ~ {end_date}")
    df = fetch_from_baostock(symbol, start_date, end_date)
    if df is None or df.empty:
        return symbol, "no_data"

    # 统一日期格式
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    if filepath.exists():
        df_old = pd.read_csv(filepath)
        df_old["date"] = pd.to_datetime(df_old["date"]).dt.strftime("%Y-%m-%d")
        df_combined = pd.concat([df_old, df], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=["date"], keep="last")
        df_combined = df_combined.sort_values("date").reset_index(drop=True)
        df_combined.to_csv(filepath, index=False)
        log.info(f"  ✓ {symbol}: 合并后共 {len(df_combined)} 条")
    else:
        df.to_csv(filepath, index=False)
        log.info(f"  ✓ {symbol}: 新建 {len(df)} 条")

    return symbol, "updated"


def main():
    print("=" * 60)
    print(f"批量抓取股票数据 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("数据源: BaoStock（AKShare 已永久移除）")
    print("=" * 60)

    # 读取所有 CSV 文件
    csv_files = sorted([f for f in DATA_DIR.glob("*.csv") if f.stem.isdigit()])
    symbols = [f.stem for f in csv_files]
    print(f"找到 {len(symbols)} 个股票文件\n")

    start_time = time.time()
    updated = 0
    skipped = 0
    no_data = 0

    # 先登录 BaoStock（全局复用）
    try:
        _bs_ensure_login()
        log.info("BaoStock 全局登录成功")
    except RuntimeError as e:
        log.error(f"BaoStock 登录失败: {e}")
        return

    for i, symbol in enumerate(symbols):
        print(f"📈 ({i+1}/{len(symbols)}) {symbol}:")
        _, status = update_stock(symbol)
        if status == "updated":
            updated += 1
        elif status == "skipped":
            skipped += 1
        else:
            no_data += 1

        # 每只股票之间随机延迟，避免被限流
        if i < len(symbols) - 1:
            delay = random.uniform(0.3, 0.8)
            time.sleep(delay)

    elapsed = time.time() - start_time
    # 登出 BaoStock
    try:
        import baostock as bs
        bs.logout()
    except Exception:
        pass

    print(f"\n{'=' * 60}")
    print(f"完成! 更新: {updated}, 跳过(已有今日): {skipped}, 无数据: {no_data}")
    print(f"耗时: {elapsed:.1f}s ({elapsed/60:.1f}分钟)")
    print(f"数据源: BaoStock（AKShare 已永久移除）")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
