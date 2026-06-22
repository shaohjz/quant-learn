#!/usr/bin/env python3
"""
补数据脚本 - 获取缺失的交易日数据
"""

import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from data_integrity_check import get_latest_trade_date, DATA_DIR

def fetch_missing_data(symbol, start_date, end_date):
    """获取缺失的数据"""
    try:
        # 导入数据源管理器
        from data_source_manager import DataSourceManager
        dsm = DataSourceManager()
        
        # 获取数据
        df = dsm.fetch_data(symbol, start_date, end_date, adjust="qfq")
        return df
    except Exception as e:
        print(f"  获取 {symbol} 数据失败: {e}")
        return None

def backfill_data():
    """补数据主函数"""
    print("开始检查并补数据...")
    
    # 获取所有CSV文件
    csv_files = list(DATA_DIR.glob("*.csv"))
    
    if not csv_files:
        print("未找到CSV数据文件")
        return
    
    # 获取最新交易日
    latest_trade_date = get_latest_trade_date()
    print(f"最新交易日: {latest_trade_date}")
    
    # 检查每个文件
    need_update = []
    
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            df['date'] = pd.to_datetime(df['date'])
            latest_data_date = df['date'].max().strftime('%Y%m%d')
            
            # 如果数据不是最新的
            if latest_data_date < latest_trade_date:
                symbol = csv_file.stem  # 文件名就是股票代码
                need_update.append({
                    'file': csv_file,
                    'symbol': symbol,
                    'latest_date': latest_data_date
                })
                print(f"  📌 {csv_file.name}: 最新数据 {latest_data_date}，需要更新到 {latest_trade_date}")
        except Exception as e:
            print(f"  ❌ 检查 {csv_file.name} 失败: {e}")
    
    if not need_update:
        print("\n✅ 所有数据都是最新的，无需补数据")
        return
    
    print(f"\n发现 {len(need_update)} 个文件需要更新")
    
    # 询问是否补数据
    print("\n开始补数据...")
    
    success_count = 0
    fail_count = 0
    
    for item in need_update:
        csv_file = item['file']
        symbol = item['symbol']
        latest_date = item['latest_date']
        
        # 计算开始日期（最新数据日期的下一天）
        start_date = (datetime.strptime(latest_date, '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')
        
        print(f"\n处理 {symbol} ({csv_file.name})...")
        print(f"  补充范围: {start_date} ~ {latest_trade_date}")
        
        # 获取数据
        new_data = fetch_missing_data(symbol, start_date, latest_trade_date)
        
        if new_data is not None and not new_data.empty:
            # 追加到CSV文件
            new_data.to_csv(csv_file, mode='a', header=False, index=False)
            print(f"  ✅ 成功补充 {len(new_data)} 条数据")
            success_count += 1
        else:
            print(f"  ⚠️  未获取到新数据")
            fail_count += 1
    
    print(f"\n补数据完成:")
    print(f"  ✅ 成功: {success_count}")
    print(f"  ❌ 失败: {fail_count}")

if __name__ == "__main__":
    backfill_data()
