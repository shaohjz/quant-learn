#!/usr/bin/env python3
"""
A股日线数据获取脚本
支持多数据源冗余（BaoStock > Tushare > AKShare）
"""

import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta
from scripts.data_source_manager import DataSourceManager

# 默认配置
DEFAULT_STOCKS = {
    "000967": "盈峰环境",
    "002256": "兆新股份",
}

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# 初始化数据源管理器
data_source_manager = DataSourceManager()


def fetch_stock_data(symbol: str, start_date: str, end_date: str, adjust: str = "qfq") -> pd.DataFrame:
    """
    拉取单只股票的日线数据（使用多数据源冗余）

    Args:
        symbol: 股票代码，如 "000967"
        start_date: 起始日期，格式 "YYYYMMDD"
        end_date: 结束日期，格式 "YYYYMMDD"
        adjust: 复权类型，默认 "qfq"（前复权）

    Returns:
        DataFrame with columns: date, open, high, low, close, volume
        
    Raises:
        RuntimeError: 所有数据源均失败
    """
    print(f"  正在拉取 {symbol} 的日线数据 ({start_date} ~ {end_date})...")
    
    try:
        # 使用数据源管理器（多数据源冗余）
        df = data_source_manager.fetch_data(symbol, start_date, end_date, adjust)
        return df
        
    except RuntimeError as e:
        # 所有数据源均失败，记录详细错误
        error_msg = f"""
❌ 所有数据源均失败，无法获取 {symbol} 的数据

错误详情:
{str(e)}

建议:
1. 检查网络连接
2. 检查数据源 API 状态
3. 查看日志获取更多信息
"""
        print(error_msg)
        raise RuntimeError(error_msg)


# fetch_with_baostock 已迁移到 scripts/data_source_manager.py
# 保留此函数以兼容旧代码（已弃用，将在下个版本移除）
def fetch_with_baostock(symbol: str, start_date: str, end_date: str):
    """
    [已弃用] 请使用 data_source_manager.fetch_data()
    保留此函数仅为了向后兼容
    """
    import warnings
    warnings.warn("fetch_with_baostock() 已弃用，请使用 DataSourceManager", DeprecationWarning)
    
    try:
        return data_source_manager.fetch_data(symbol, start_date, end_date)
    except Exception as e:
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
    print(f"A股日线数据获取（多数据源冗余）")
    print(f"时间范围: {start_date} ~ {end_date}")
    print(f"股票列表: {', '.join(f'{v}({k})' if v else k for k, v in stocks.items())}")
    print(f"数据源优先级: {' > '.join(DataSourceManager.SOURCE_PRIORITY)}")
    print(f"=" * 60)

    # 显示数据源状态
    print("\n数据源状态:")
    health = data_source_manager.health_check()
    for source, is_healthy in health.items():
        status = '✓' if is_healthy else '✗'
        print(f"  {status} {source}")
    print()

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
