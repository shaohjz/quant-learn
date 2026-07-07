#!/usr/bin/env python3
"""
补数据脚本 - 更新所有股票的最新数据
"""
import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from data_source_manager import DataSourceManager

data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
data_dir = os.path.abspath(data_dir)

codes = [f.replace('.csv', '') for f in os.listdir(data_dir) if f.endswith('.csv')]

end_date = datetime.now().strftime('%Y%m%d')
start_date = '20260615'

print(f"开始补数据: {start_date} ~ {end_date}")
print(f"股票数: {len(codes)}")
print()

mgr = DataSourceManager()
print("数据源状态:")
health = mgr.health_check()
for src, ok in health.items():
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] {src}")
print()

success = 0
failed = 0
skipped = 0
errors = []

for i, code in enumerate(codes):
    fpath = os.path.join(data_dir, f"{code}.csv")
    try:
        df_existing = pd.read_csv(fpath)
        df_existing['date'] = pd.to_datetime(df_existing['date'])
        last_date = df_existing['date'].max()
        
        # 如果最新数据已到昨天或今天，跳过
        expected = pd.Timestamp('2026-06-25')
        if last_date >= expected:
            skipped += 1
            continue
        
        fetch_start = (last_date + timedelta(days=1)).strftime('%Y%m%d')
        fetch_end = end_date
        
        print(f"[{i+1}/{len(codes)}] {code}: 补 {fetch_start}~{fetch_end}...", end=" ")
        
        df_new = mgr.fetch_data(code, fetch_start, fetch_end)
        
        if df_new is not None and len(df_new) > 0:
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            df_combined = df_combined.drop_duplicates(subset=['date']).sort_values('date')
            df_combined.to_csv(fpath, index=False)
            new_last = df_combined['date'].max().strftime('%Y-%m-%d')
            print(f"OK 新增 {len(df_new)} 条，最新: {new_last}")
            success += 1
        else:
            print("NO NEW DATA")
            failed += 1
        
        time.sleep(0.5)
        
    except Exception as e:
        err_msg = str(e)[:100]
        print(f"FAIL: {err_msg}")
        errors.append({"code": code, "error": err_msg})
        failed += 1

print()
print("=== 补数据完成 ===")
print(f"成功: {success}")
print(f"失败: {failed}")
print(f"无需更新: {skipped}")

if errors:
    print()
    print("=== 失败详情 ===")
    for e in errors:
        print(f"  {e['code']}: {e['error']}")

# 保存结果
result = {
    "time": datetime.now().isoformat(),
    "success": success,
    "failed": failed,
    "skipped": skipped,
    "errors": errors
}
output_path = os.path.join(data_dir, f"refetch_result_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
with open(output_path, 'w', encoding='utf-8') as f:
    import json
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"\n结果已保存: {output_path}")
