#!/usr/bin/env python3
"""
使用 baostock 补数据 - 只要 baostock 可用就补
"""
import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta
import baostock as bs

data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
data_dir = os.path.abspath(data_dir)

codes = [f.replace('.csv', '') for f in os.listdir(data_dir) if f.endswith('.csv')]

end_date = datetime.now().strftime('%Y-%m-%d')
# baostock 数据有延迟，通常到昨天
fetch_end = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

print(f"使用 baostock 补数据")
print(f"目标最新日期: {fetch_end}")
print(f"股票数: {len(codes)}")
print()

# 登录 baostock
lg = bs.login()
if lg.error_code != '0':
    print(f"baostock 登录失败: {lg.error_msg}")
    sys.exit(1)
print("baostock 登录成功\n")

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
        
        # 如果最新数据已到昨天，跳过
        expected = pd.Timestamp(fetch_end)
        if last_date >= expected:
            skipped += 1
            continue
        
        fetch_start = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')
        
        print(f"[{i+1}/{len(codes)}] {code}: {fetch_start}~{fetch_end}...", end=" ")
        
        # 使用 baostock 获取的数据
        # 注意：baostock 需要股票代码带 sh/sz 前缀，日期格式 YYYY-MM-DD
        if code.startswith('6'):
            bs_code = f"sh.{code}"
        else:
            bs_code = f"sz.{code}"
        
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,code,open,high,low,close,volume",
            start_date=fetch_start,
            end_date=fetch_end,
            frequency="d",
            adjustflag="2"  # 2=前复权
        )
        
        if rs is None:
            print("FAIL (rs=None)")
            failed += 1
            continue
        
        if rs.error_code != '0':
            print(f"FAIL (bs: {rs.error_msg})")
            failed += 1
            continue
        
        data_list = []
        while (rs.error_code == '0') and rs.next():
            data_list.append(rs.get_row_data())
        
        if not data_list:
            print("NO DATA")
            failed += 1
            continue
        
        df_new = pd.DataFrame(data_list, columns=['date','code','open','high','low','close','volume'])
        df_new = df_new[df_new['date'] != '']
        if len(df_new) == 0:
            print("EMPTY")
            failed += 1
            continue
        
        # 类型转换
        for col in ['open','high','low','close','volume']:
            df_new[col] = pd.to_numeric(df_new[col], errors='coerce')
        df_new['date'] = pd.to_datetime(df_new['date'])
        
        # 合并
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=['date']).sort_values('date')
        df_combined.to_csv(fpath, index=False)
        
        new_last = df_combined['date'].max().strftime('%Y-%m-%d')
        print(f"OK +{len(df_new)}条 -> {new_last}")
        success += 1
        
        time.sleep(0.2)
        
    except Exception as e:
        err_msg = str(e)[:80]
        print(f"ERR: {err_msg}")
        errors.append({"code": code, "error": err_msg})
        failed += 1

# 登出
bs.logout()

print()
print("=== 补数据完成 ===")
print(f"成功: {success}")
print(f"失败: {failed}")
print(f"无需更新: {skipped}")

if errors:
    print()
    print("=== 失败详情 ===")
    for e in errors[:10]:
        print(f"  {e['code']}: {e['error']}")

# 保存结果
import json
result = {
    "time": datetime.now().isoformat(),
    "source": "baostock",
    "success": success,
    "failed": failed,
    "skipped": skipped,
    "errors": errors
}
output_path = os.path.join(data_dir, f"refetch_result_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print(f"\n结果已保存: {output_path}")
