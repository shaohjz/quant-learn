#!/usr/bin/env python3
"""
测试数据源管理器（Mock测试，不依赖外部API）
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')

from unittest.mock import Mock, patch
import pandas as pd
from scripts.data_source_manager import DataSourceManager

def test_data_source_priority():
    """测试数据源优先级"""
    manager = DataSourceManager()
    
    # 验证优先级顺序
    assert manager.SOURCE_PRIORITY == ['baostock', 'tushare', 'akshare']
    print("✓ 数据源优先级正确")

def test_column_normalization():
    """测试列名标准化"""
    manager = DataSourceManager()
    
    # 测试 AKShare 格式（中文列名）
    df_zh = pd.DataFrame({
        '日期': ['2026-06-10', '2026-06-11'],
        '开盘': [10.0, 10.5],
        '最高': [10.2, 10.7],
        '最低': [9.8, 10.3],
        '收盘': [10.1, 10.6],
        '成交量': [1000000, 1200000]
    })
    
    result = manager._normalize_columns(df_zh)
    assert list(result.columns) == ['date', 'open', 'high', 'low', 'close', 'volume']
    assert len(result) == 2
    print("✓ AKShare 列名标准化正确")
    
    # 测试已经是英文列名
    df_en = pd.DataFrame({
        'date': ['2026-06-10', '2026-06-11'],
        'open': [10.0, 10.5],
        'high': [10.2, 10.7],
        'low': [9.8, 10.3],
        'close': [10.1, 10.6],
        'volume': [1000000, 1200000]
    })
    
    result2 = manager._normalize_columns(df_en)
    assert list(result2.columns) == ['date', 'open', 'high', 'low', 'close', 'volume']
    print("✓ 英文列名处理正确")

def test_baostock_fallback():
    """测试 BaoStock 兜底（Mock）"""
    manager = DataSourceManager()
    
    # Mock BaoStock 成功
    with patch.object(manager, '_fetch_from_baostock') as mock_baostock:
        mock_baostock.return_value = pd.DataFrame({
            'date': ['2026-06-10'],
            'open': [10.0],
            'high': [10.2],
            'low': [9.8],
            'close': [10.1],
            'volume': [1000000]
        })
        
        # Mock AKShare 失败
        with patch.object(manager, '_fetch_from_akshare', side_effect=Exception("Connection failed")):
            # 应该自动切换到 BaoStock
            result = manager.fetch_data('000001', '20260610', '20260616')
            assert len(result) == 1
            print("✓ BaoStock 兜底机制正常")

def test_all_sources_fail():
    """测试所有数据源均失败"""
    manager = DataSourceManager()
    
    # Mock 所有数据源都失败
    with patch.object(manager, '_fetch_from_baostock', side_effect=Exception("BaoStock failed")):
        with patch.object(manager, '_fetch_from_tushare', side_effect=Exception("Tushare failed")):
            with patch.object(manager, '_fetch_from_akshare', side_effect=Exception("AKShare failed")):
                try:
                    manager.fetch_data('000001', '20260610', '20260616')
                    assert False, "应该抛出异常"
                except RuntimeError as e:
                    assert "所有数据源均失败" in str(e)
                    print("✓ 所有数据源失败时正确抛出异常")

def test_health_check():
    """测试健康检查（Mock）"""
    manager = DataSourceManager()
    
    # Mock 所有数据源都健康
    with patch.object(manager, '_fetch_from_baostock') as mock_bs:
        mock_bs.return_value = pd.DataFrame({'date': ['2026-06-10']})
        
        health = manager.health_check()
        assert health['baostock'] == True
        print("✓ 健康检查正常")

if __name__ == "__main__":
    print("="*60)
    print("数据源管理器单元测试")
    print("="*60 + "\n")
    
    try:
        test_data_source_priority()
        test_column_normalization()
        test_baostock_fallback()
        test_all_sources_fail()
        test_health_check()
        
        print("\n" + "="*60)
        print("✅ 所有测试通过")
        print("="*60)
        
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 意外错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
