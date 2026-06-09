#!/usr/bin/env python3
"""自动补数据脚本 - 从最后日期补到最新交易日"""

import os
import sys
import time
import json
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path("data")

def get_last_date(csv_file):
    """获取CSV文件的最后日期"""
    try:
        df = pd.read_csv(csv_file, nrows=1, skiprows=1, header=None)
        # 读最后一行
        df = pd.read_csv(csv_file)
        if df.empty:
            return None
        last_date = df['date'].iloc[-1]
        return str(last_date)
    except Exception as e:
        print(f"  读取最后日期失败: {e}")
        return None

def fetch_stock_data(symbol, start_date, end_date):
    """拉取单只股票数据"""
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            adjust="qfq",
        )
        if df is None or df.empty:
            return None
        
        # 统一列名
        col_map = {
            "日期": "date", "开盘": "open", "最高": "high",
            "最低": "low", "收盘": "close", "成交量": "volume",
        }
        available = [c for c in col_map if c in df.columns]
        if available:
            df = df[available].rename(columns=col_map)
        else:
            # 已经是英文列名
            df = df[["date","open","high","low","close","volume"]]
        
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open","high","low","close"]:
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(float)
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  ⚠ 拉取 {symbol} 失败: {e}")
        return None

def backfill_stock(symbol, csv_file):
    """补单只股票的数据"""
    last_date = get_last_date(csv_file)
    if last_date is None:
        print(f"  {symbol}: 无法读取最后日期，跳过")
        return False
    
    # 下一天开始
    last_dt = datetime.strptime(last_date, '%Y-%m-%d')
    next_dt = last_dt + timedelta(days=1)
    today = datetime.now().date()
    
    if next_dt.date() > today:
        print(f"  {symbol}: 数据已是最新 ({last_date})")
        return True
    
    start_str = next_dt.strftime('%Y-%m-%d')
    end_str = today.strftime('%Y-%m-%d')
    
    print(f"  {symbol}: 补数据 {start_str} ~ {end_str}")
    
    df_new = fetch_stock_data(symbol, start_str, end_str)
    if df_new is None or df_new.empty:
        print(f"  {symbol}: 无新数据（可能非交易日）")
        return True  # 非交易日不是错误
    
    # 合并到原文件
    df_old = pd.read_csv(csv_file)
    df_combined = pd.concat([df_old, df_new], ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset=['date'], keep='last')
    df_combined = df_combined.sort_values('date').reset_index(drop=True)
    df_combined.to_csv(csv_file, index=False)
    
    print(f"  {symbol}: ✓ 补了 {len(df_new)} 条，现共 {len(df_combined)} 条")
    return True

def main():
    print("=" * 60)
    print(f"自动补数据 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    csv_files = sorted([f for f in DATA_DIR.glob("*.csv") if f.stem.isdigit()])
    print(f"找到 {len(csv_files)} 个股票文件\n")
    
    success = 0
    failed = 0
    
    for csv_file in csv_files:
        symbol = csv_file.stem
        print(f"📈 {symbol}:")
        try:
            ok = backfill_stock(symbol, csv_file)
            if ok:
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ❌ 错误: {e}")
            failed += 1
        time.sleep(0.5)  # 避免请求过快
    
    print(f"\n{'=' * 60}")
    print(f"完成: 成功 {success}, 失败 {failed}")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()
