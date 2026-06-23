#!/usr/bin/env python3
"""
测试所有数据源的连通性
"""
import sys
import os
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

from scripts.data_source_manager import DataSourceManager, CurlHttpFetcher

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_all_sources():
    """测试所有数据源"""
    print("=" * 60)
    print("数据源连通性测试")
    print("=" * 60)
    
    manager = DataSourceManager()
    
    # 测试股票代码
    test_symbol = "000001"  # 平安银行
    test_start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    test_end = datetime.now().strftime("%Y%m%d")
    
    results = {}
    
    # 测试每个数据源
    for source in manager.SOURCE_PRIORITY:
        print(f"\n--- 测试数据源: {source} ---")
        try:
            df = manager._fetch_from_source(source, test_symbol, test_start, test_end, "qfq")
            if df is not None and len(df) > 0:
                print(f"✓ {source}: 成功获取 {len(df)} 行数据")
                print(f"  最新数据: {df['date'].max()}")
                results[source] = True
            else:
                print(f"✗ {source}: 返回空数据")
                results[source] = False
        except Exception as e:
            print(f"✗ {source}: 失败 - {e}")
            results[source] = False
    
    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    available = [s for s, ok in results.items() if ok]
    unavailable = [s for s, ok in results.items() if not ok]
    
    if available:
        print(f"✓ 可用数据源 ({len(available)}): {', '.join(available)}")
    else:
        print("✗ 所有数据源均不可用！")
    
    if unavailable:
        print(f"✗ 不可用数据源 ({len(unavailable)}): {', '.join(unavailable)}")
    
    return results

if __name__ == "__main__":
    test_all_sources()
