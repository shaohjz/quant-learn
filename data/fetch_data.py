#!/usr/bin/env python3
"""
A股日线数据获取脚本
使用 AKShare 的 stock_zh_a_hist 接口拉取前复权日线数据，保存为 CSV。
"""

import os
import sys
import time
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta

# 默认配置
DEFAULT_STOCKS = {
    "000967": "盈峰环境",
    "002256": "兆新股份",
}

DATA_DIR = os.path.dirname(os.path.abspath(__file__))


def fetch_stock_data(symbol: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
    """
    拉取单只股票的日线数据

    Args:
        symbol: 股票代码，如 "000967"
        start_date: 起始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"
        adjust: 复权类型，默认 "qfq"（前复权）

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    print(f"  正在拉取 {symbol} 的日线数据 ({start_date} ~ {end_date})...")

    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
    except Exception as e:
        print(f"  ⚠ AKShare 拉取失败: {e}")
        print(f"  尝试使用 BaoStock 备选方案...")
        df = fetch_with_baostock(symbol, start_date, end_date)
        if df is None:
            raise RuntimeError(f"所有数据源均失败，无法获取 {symbol} 的数据")

    # 统一列名：处理中文列名（AKShare）和英文列名（BaoStock）
    target_cols = ["date", "open", "high", "low", "close", "volume"]
    if all(c in df.columns for c in target_cols):
        # 已经是英文列名（BaoStock），直接取
        df = df[target_cols]
    else:
        col_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
        available_cols = [c for c in col_map.keys() if c in df.columns]
        df = df[available_cols].rename(columns=col_map)

    # 确保数据类型正确
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(float)

    # 按日期排序
    df = df.sort_values("date").reset_index(drop=True)

    return df


def fetch_with_baostock(symbol: str, start_date: str, end_date: str):
    """BaoStock 备选方案"""
    try:
        import baostock as bs

        lg = bs.login()
        if lg.error_code != "0":
            print(f"  BaoStock 登录失败: {lg.error_msg}")
            return None

        # BaoStock 需要 sh/sz 前缀
        prefix = "sh" if symbol.startswith("6") else "sz"
        bs_code = f"{prefix}.{symbol}"
        sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume",
            start_date=sd,
            end_date=ed,
            frequency="d",
            adjustflag="2",  # 前复权
        )

        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())

        bs.logout()

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        return df

    except ImportError:
        print("  BaoStock 未安装，跳过备选方案")
        return None
    except Exception as e:
        print(f"  BaoStock 也失败了: {e}")
        return None


def save_to_csv(df: pd.DataFrame, symbol: str, name: str = ""):
    """保存数据到 CSV"""
    filepath = os.path.join(DATA_DIR, f"{symbol}.csv")
    df.to_csv(filepath, index=False)
    label = f"{name}({symbol})" if name else symbol
    print(f"  ✓ {label} 数据已保存: {filepath} ({len(df)} 条记录)")
    return filepath


def main():
    """主函数"""
    # 解析命令行参数
    if len(sys.argv) >= 4:
        stocks = {sys.argv[1]: ""}
        start_date = sys.argv[2]
        end_date = sys.argv[3]
    else:
        stocks = DEFAULT_STOCKS
        # 默认拉取最近2年的数据
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=730)).strftime("%Y%m%d")

    print(f"=" * 60)
    print(f"A股日线数据获取")
    print(f"时间范围: {start_date} ~ {end_date}")
    print(f"股票列表: {', '.join(f'{v}({k})' if v else k for k, v in stocks.items())}")
    print(f"=" * 60)

    for symbol, name in stocks.items():
        try:
            df = fetch_stock_data(symbol, start_date, end_date)
            save_to_csv(df, symbol, name)
            # 接口调用间隔，避免被限流
            time.sleep(1)
        except Exception as e:
            print(f"  ✗ {name}({symbol}) 获取失败: {e}")

    print(f"\n数据获取完成！")


if __name__ == "__main__":
    main()
