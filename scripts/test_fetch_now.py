#!/usr/bin/env python3
"""快速测试当前可用的数据源"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

from scripts.data_source_manager import CurlHttpFetcher, DataSourceManager
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 200)

print("=" * 60)
print("数据源连通性测试 (内网环境)")
print("=" * 60)

# Test 1: 新浪实时行情
print("\n--- Test 1: 新浪实时行情 (HTTP, 无SSL) ---")
try:
    result = CurlHttpFetcher.fetch_sina_realtime(['sh000001', 'sz399001', 'sh600000'])
    if result:
        for k, v in result.items():
            print(f"  {k}: {v}")
    else:
        print("  ❌ 返回空")
except Exception as e:
    print(f"  ❌ 失败: {e}")

# Test 2: 新浪K线
print("\n--- Test 2: 新浪K线 (000001 平安银行) ---")
try:
    df = CurlHttpFetcher.fetch_sina_kline('000001', '20260610', '20260623')
    if df is not None and len(df) > 0:
        print(f"  ✓ 成功! 行数: {len(df)}, 最新日期: {df['date'].max()}")
        print(df.tail(3).to_string())
    else:
        print("  ❌ 返回空")
except Exception as e:
    print(f"  ❌ 失败: {e}")

# Test 3: 东方财富K线
print("\n--- Test 3: 东方财富K线 (000001 平安银行) ---")
try:
    df2 = CurlHttpFetcher.fetch_eastmoney_kline('000001', '20260610', '20260623')
    if df2 is not None and len(df2) > 0:
        print(f"  ✓ 成功! 行数: {len(df2)}, 最新日期: {df2['date'].max()}")
        print(df2.tail(3).to_string())
    else:
        print("  ❌ 返回空")
except Exception as e:
    print(f"  ❌ 失败: {e}")

# Test 4: DataSourceManager 完整获取
print("\n--- Test 4: DataSourceManager.fetch_data (000001) ---")
try:
    manager = DataSourceManager()
    df3 = manager.fetch_data('000001', '20260610', '20260623')
    if df3 is not None and len(df3) > 0:
        print(f"  ✓ 成功! 行数: {len(df3)}, 最新日期: {df3['date'].max()}")
        print(df3.tail(3).to_string())
    else:
        print("  ❌ 返回空")
except Exception as e:
    print(f"  ❌ 失败: {e}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
