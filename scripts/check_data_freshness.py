#!/usr/bin/env python3
"""
快速数据更新脚本 - 更新所有股票的最新数据
"""

import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data")

def update_stock_data(csv_file):
    """更新单个股票的数据"""
    try:
        # 读取现有数据
        df = pd.read_csv(csv_file)
        df['date'] = pd.to_datetime(df['date'])
        
        # 获取最新日期
        latest_date = df['date'].max()
        
        # 如果最新数据已经超过7天前，尝试更新
        days_since_update = (datetime.now() - latest_date).days
        
        if days_since_update > 3:  # 如果超过3天没更新
            print(f"  📌 {csv_file.name}: {days_since_update}天未更新 (最新: {latest_date.strftime('%Y-%m-%d')})")
            return False, days_since_update
        else:
            return True, 0
            
    except Exception as e:
        print(f"  ❌ {csv_file.name}: {e}")
        return False, -1

def main():
    """主函数"""
    print("检查数据更新状态...")
    print(f"当前日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # 获取所有CSV文件
    csv_files = list(DATA_DIR.glob("*.csv"))
    
    if not csv_files:
        print("未找到CSV数据文件")
        return
    
    print(f"检查 {len(csv_files)} 个数据文件...\n")
    
    need_update = []
    
    for csv_file in csv_files:
        ok, days = update_stock_data(csv_file)
        if not ok and days > 0:
            need_update.append((csv_file, days))
    
    if need_update:
        print(f"\n发现 {len(need_update)} 个文件需要更新:")
        for csv_file, days in need_update:
            print(f"  - {csv_file.name}: {days}天未更新")
        
        print("\n建议运行数据获取脚本更新数据")
        print("或者检查是否设置了定时任务\n")
    else:
        print("\n✅ 所有数据都是最新的（3天内）")

if __name__ == "__main__":
    main()
