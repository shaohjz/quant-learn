#!/usr/bin/env python3
"""
A股日线数据获取脚本（BaoStock 主力，AKShare 已永久移除）
使用 BaoStock 拉取前复权日线数据，保存为 CSV。
AKShare 已永久移除（连续 7 天不可用，2026-06-16）
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_fetch.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_STOCKS = {
    "000967": "盈峰环境",
    "002256": "兆新股份",
}

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒


def fetch_stock_data(symbol: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
    """
    拉取单只股票的日线数据（BaoStock 主力，AKShare 已永久移除）
    
    Args:
        symbol: 股票代码，如 "000967"
        start_date: 起始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"
        adjust: 复权类型，默认 "qfq"（前复权）
    
    Returns:
        DataFrame with columns: date, open, high, low, close, volume
    """
    logger.info(f"正在拉取 {symbol} 的日线数据 ({start_date} ~ {end_date})...")
    
    # 策略1: 尝试 BaoStock（主力数据源）
    logger.info(f"  尝试 BaoStock...")
    df = fetch_with_baostock(symbol, start_date, end_date)
    if df is not None and not df.empty:
        logger.info(f"  ✓ BaoStock 拉取成功")
        return normalize_dataframe(df, source="baostock")
    
    # 策略2: 尝试 Tushare (如果配置了 token)
    logger.info(f"  尝试使用 Tushare 备选方案...")
    df = fetch_with_tushare(symbol, start_date, end_date)
    if df is not None and not df.empty:
        logger.info(f"  ✓ Tushare 拉取成功")
        return normalize_dataframe(df, source="tushare")
    
    # 所有数据源都失败
    error_msg = f"所有数据源均失败，无法获取 {symbol} 的数据"
    logger.error(error_msg)
    raise RuntimeError(error_msg)


def normalize_dataframe(df: pd.DataFrame, source: str = "akshare") -> pd.DataFrame:
    """
    统一不同数据源的 DataFrame 格式
    
    Args:
        df: 原始数据 DataFrame
        source: 数据源类型 (akshare/baostock/tushare)
    
    Returns:
        标准化后的 DataFrame
    """
    target_cols = ["date", "open", "high", "low", "close", "volume"]
    
    if source == "akshare":
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
    elif source == "baostock":
        # BaoStock 已经是英文列名
        df = df[target_cols]
    elif source == "tushare":
        # Tushare 列名处理
        col_map = {
            "trade_date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "vol": "volume",
        }
        df = df.rename(columns=col_map)
        df = df[target_cols]
    
    # 确保数据类型正确
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(float)
    
    # 按日期排序
    df = df.sort_values("date").reset_index(drop=True)
    
    return df


def fetch_with_baostock(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """BaoStock 备选方案"""
    try:
        import baostock as bs
        
        lg = bs.login()
        if lg.error_code != "0":
            logger.warning(f"  BaoStock 登录失败: {lg.error_msg}")
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
            logger.warning(f"  BaoStock 未返回数据")
            return None
        
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        return df
        
    except ImportError:
        logger.warning("  BaoStock 未安装，跳过备选方案")
        return None
    except Exception as e:
        logger.warning(f"  BaoStock 也失败了: {e}")
        return None


def fetch_with_tushare(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """Tushare 备选方案"""
    try:
        import tushare as ts
        
        # 检查是否配置了 token
        import os
        token = os.getenv("TUSHARE_TOKEN")
        if not token:
            logger.warning("  Tushare token 未配置，跳过")
            return None
        
        ts.set_token(token)
        pro = ts.pro_api()
        
        # Tushare 需要年月日格式
        start = f"{start_date[:4]}{start_date[4:6]}{start_date[6:]}"
        end = f"{end_date[:4]}{end_date[4:6]}{end_date[6:]}"
        
        df = pro.daily(ts_code=f"{symbol}.SZ" if symbol.startswith(("0", "3")) else f"{symbol}.SH",
                       start_date=start, end_date=end)
        
        if df is not None and not df.empty:
            return df
        return None
    except ImportError:
        logger.warning("  Tushare 未安装，跳过备选方案")
        return None
    except Exception as e:
        logger.warning(f"  Tushare 也失败了: {e}")
        return None


def save_to_csv(df: pd.DataFrame, symbol: str, name: str = "") -> str:
    """保存数据到 CSV"""
    filepath = os.path.join(DATA_DIR, f"{symbol}.csv")
    df.to_csv(filepath, index=False)
    label = f"{name}({symbol})" if name else symbol
    logger.info(f"  ✓ {label} 数据已保存: {filepath} ({len(df)} 条记录)")
    return filepath


def send_alert(symbol: str, message: str):
    """发送告警通知（可集成到企微/邮件）"""
    # TODO: 实现企微机器人告警
    logger.error(f"ALERT - {symbol}: {message}")
    pass


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
    
    success_count = 0
    fail_count = 0
    
    for symbol, name in stocks.items():
        try:
            df = fetch_stock_data(symbol, start_date, end_date)
            save_to_csv(df, symbol, name)
            
            # 发送成功通知（可选）
            # send_notification(f"{symbol} 数据更新成功，{len(df)} 条记录")
            
            # 接口调用间隔，避免被限流
            time.sleep(1)
            success_count += 1
        except Exception as e:
            error_msg = f"{name}({symbol}) 获取失败: {e}"
            logger.error(f"  ✗ {error_msg}")
            # 发送失败告警
            send_alert(symbol, error_msg)
            fail_count += 1
    
    print(f"\n数据获取完成！成功: {success_count}, 失败: {fail_count}")
    logger.info(f"数据获取完成！成功: {success_count}, 失败: {fail_count}")


if __name__ == "__main__":
    main()
