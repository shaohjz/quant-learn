#!/usr/bin/env python3
"""
更新剩余的12个股票数据
"""
import baostock as bs
import pandas as pd
import time
from datetime import datetime, timedelta

stale_codes = ['000301','000858','000967','002405','002594','300059','300124','60036','600310','600563','601318','601728']

# 注意：上面列表里 '60036' 应该是 '600036'，修正一下
stale_codes = ['000301','000858','000967','002405','002594','300059','300124','600036','600310','600563','601318','601728']

print("更新剩余12个股票...")
print()

# 登录
lg = bs.login()
print(f"登录: {lg.error_msg}")
print()

success = 0
failed = []

for code in stale_codes:
    try:
        fpath = f"data/{code}.csv"
        df_existing = pd.read_csv(fpath)
        df_existing['date'] = pd.to_datetime(df_existing['date'])
        last_date = df_existing['date'].max()
        fetch_start = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')
        fetch_end = '2026-06-25'
        
        print(f"{code}: {fetch_start}~{fetch_end}...", end=" ")
        
        bs_code = f"sh.{code}" if code.startswith('6') else f"sz.{code}"
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,code,open,high,low,close,volume",
            start_date=fetch_start, end_date=fetch_end,
            frequency="d", adjustflag="2"
        )
        
        if rs is None or rs.error_code != '0':
            # 尝试重新登录
            try:
                bs.logout()
            except:
                pass
            time.sleep(1)
            lg2 = bs.login()
            print(f"重登录: {lg2.error_msg}", end=" ")
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,volume",
                start_date=fetch_start, end_date=fetch_end,
                frequency="d", adjustflag="2"
            )
        
        if rs is None:
            print("FAIL: rs=None")
            failed.append(code)
            continue
            
        if rs.error_code != '0':
            err = rs.error_msg
            print(f"FAIL: {err}")
            failed.append(code)
            continue
        
        data_list = []
        while rs.next():
            data_list.append(rs.get_row_data())
        
        if not data_list:
            print("NO DATA")
            failed.append(code)
            continue
        
        df_new = pd.DataFrame(data_list, columns=["date","code","open","high","low","close","volume"])
        df_new = df_new[df_new["date"] != ""]
        for col in ["open","high","low","close","volume"]:
            df_new[col] = pd.to_numeric(df_new[col], errors="coerce")
        df_new["date"] = pd.to_datetime(df_new["date"])
        
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined = df_combined.drop_duplicates(subset=["date"]).sort_values("date")
        df_combined.to_csv(fpath, index=False)
        new_last = df_combined["date"].max().strftime("%Y-%m-%d")
        print(f"OK -> {new_last}")
        success += 1
        time.sleep(0.3)
        
    except Exception as e:
        err = str(e)
        print(f"ERR: {err}")
        failed.append(code)

try:
    bs.logout()
except:
    pass

print()
print(f"成功: {success}/12")
if failed:
    print(f"仍失败: {failed}")
else:
    print("全部成功！")
