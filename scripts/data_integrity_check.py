#!/usr/bin/env python3
"""数据完整性检查脚本 - 由数据Agent执行"""

import os
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path("data")
OUTPUT_DIR = Path("pm/data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 读取交易日历
trade_dates_path = DATA_DIR / "trade_dates.json"
if trade_dates_path.exists():
    with open(trade_dates_path) as f:
        TRADE_DATES = set(json.load(f))
else:
    TRADE_DATES = None

def check_csv_file(filepath):
    """检查单个CSV文件的数据完整性"""
    results = {
        "file": filepath.name,
        "status": "ok",
        "first_date": None,
        "last_date": None,
        "row_count": 0,
        "null_count": 0,
        "gap_dates": [],
        "price_jumps": [],
        "negative_values": [],
        "errors": []
    }
    
    rows = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            # 期望列: date, open, high, low, close, volume
            for row in reader:
                rows.append(row)
    except Exception as e:
        results["status"] = "error"
        results["errors"].append(f"读取文件失败: {e}")
        return results
    
    if not rows:
        results["status"] = "empty"
        results["errors"].append("文件为空")
        return results
    
    results["row_count"] = len(rows)
    
    # 解析日期和价格
    dates = []
    closes = []
    for i, row in enumerate(rows):
        if len(row) < 6:
            results["null_count"] += 1
            continue
        date_str = row[0].strip()
        try:
            dt = datetime.strptime(date_str, '%Y-%m-%d')
            dates.append((i, dt, date_str))
        except:
            results["errors"].append(f"第{i+2}行日期格式错误: {date_str}")
            continue
        
        # 检查空值
        for j, val in enumerate(row):
            if val.strip() == '':
                results["null_count"] += 1
        
        # 检查负值
        try:
            close = float(row[4])
            open_ = float(row[1])
            high = float(row[2])
            low = float(row[3])
            volume = float(row[5])
            closes.append((i, close))
            if close < 0 or open_ < 0 or high < 0 or low < 0 or volume < 0:
                results["negative_values"].append(f"{date_str}: 负值 close={close}")
        except:
            results["null_count"] += 1
    
    if not dates:
        results["status"] = "error"
        results["errors"].append("没有有效日期")
        return results
    
    # 排序日期
    dates.sort(key=lambda x: x[1])
    results["first_date"] = dates[0][2]
    results["last_date"] = dates[-1][2]
    
    # 检查日期跳变（交易日缺失）
    if TRADE_DATES:
        for i in range(len(dates) - 1):
            d1 = dates[i][2]
            d2 = dates[i+1][2]
            # 找d1之后的下一个交易日
            # 简化：检查中间是否有交易日
            dt1 = dates[i][1]
            dt2 = dates[i+1][1]
            # 生成d1到d2之间的所有日期，检查是否在交易日历中
            d = dt1 + timedelta(days=1)
            missing = []
            while d < dt2:
                d_str = d.strftime('%Y-%m-%d')
                if d_str in TRADE_DATES and d_str not in [dates[k][2] for k in range(len(dates))]:
                    missing.append(d_str)
                d += timedelta(days=1)
            if missing:
                results["gap_dates"].extend(missing[:5])  # 最多5个
    else:
        # 没有交易日历，用简单间隔检查
        for i in range(1, len(dates)):
            diff = (dates[i][1] - dates[i-1][1]).days
            if diff > 3:  # 超过3天（考虑周末）
                results["gap_dates"].append(f"{dates[i-1][2]} -> {dates[i][2]} ({diff}天)")
    
    # 检查价格跳变（涨跌幅 > 10%）
    for i in range(1, len(closes)):
        idx1, c1 = closes[i-1]
        idx2, c2 = closes[i]
        if c1 == 0:
            continue
        pct = abs((c2 - c1) / c1 * 100)
        if pct > 10:
            date_str = rows[idx2][0] if idx2 < len(rows) else "?"
            results["price_jumps"].append(f"{date_str}: {pct:.1f}%")
    
    # 判断状态
    if results["null_count"] > 0:
        results["status"] = "warning"
    if results["gap_dates"]:
        results["status"] = "warning"
    if results["price_jumps"]:
        results["status"] = "warning"
    if results["negative_values"]:
        results["status"] = "error"
    
    return results

def check_data_timeliness(last_date_str):
    """检查数据时效性 - 最后数据日期距今天数"""
    if not last_date_str:
        return None, "无数据"
    try:
        last_dt = datetime.strptime(last_date_str, '%Y-%m-%d')
        now = datetime.now()
        diff = (now - last_dt).days
        return diff, f"最后数据日期距今{diff}天"
    except:
        return None, "日期解析失败"

def main():
    print("=" * 70)
    print("数据完整性检查报告")
    print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    csv_files = sorted([f for f in DATA_DIR.glob("*.csv") if f.stem.isdigit()])
    
    all_results = []
    total_nulls = 0
    total_gaps = 0
    files_with_jumps = 0
    files_with_gaps = 0
    latest_date = None
    
    for csv_file in csv_files:
        result = check_csv_file(csv_file)
        all_results.append(result)
        total_nulls += result["null_count"]
        total_gaps += len(result["gap_dates"])
        if result["price_jumps"]:
            files_with_jumps += 1
        if result["gap_dates"]:
            files_with_gaps += 1
        
        # 追踪最新日期
        if result["last_date"]:
            try:
                d = datetime.strptime(result["last_date"], '%Y-%m-%d')
                if latest_date is None or d > latest_date:
                    latest_date = d
            except:
                pass
    
    # 输出汇总
    print(f"\n## 汇总")
    print(f"  股票文件数: {len(csv_files)}")
    print(f"  总空值数: {total_nulls}")
    print(f"  文件缺失交易日: {files_with_gaps} 个")
    print(f"  文件价格跳变: {files_with_jumps} 个")
    if latest_date:
        diff, msg = check_data_timeliness(latest_date.strftime('%Y-%m-%d'))
        print(f"  数据时效性: {msg}")
    
    # 详细结果
    print(f"\n## 详细结果（前10个）")
    print(f"{'文件':<12} {'状态':<8} {'首日期':<12} {'末日期':<12} {'行数':>6} {'空值':>5} {'缺口':>5} {'跳变':>5}")
    print("-" * 80)
    for r in all_results[:10]:
        jumps = len(r["price_jumps"])
        gaps = len(r["gap_dates"])
        print(f"{r['file']:<12} {r['status']:<8} {str(r['first_date']):<12} {str(r['last_date']):<12} {r['row_count']:>6} {r['null_count']:>5} {gaps:>5} {jumps:>5}")
    
    if len(all_results) > 10:
        print(f"  ... 还有 {len(all_results)-10} 个文件")
    
    # 问题文件
    problem_files = [r for r in all_results if r["status"] != "ok"]
    if problem_files:
        print(f"\n## 问题文件详情")
        for r in problem_files:
            print(f"\n  📁 {r['file']}: {r['status']}")
            if r["null_count"] > 0:
                print(f"    - 空值: {r['null_count']} 个")
            if r["gap_dates"]:
                print(f"    - 缺失交易日: {r['gap_dates'][:3]}")
            if r["price_jumps"]:
                print(f"    - 价格跳变: {r['price_jumps'][:3]}")
            if r["negative_values"]:
                print(f"    - 负值: {r['negative_values'][:3]}")
            if r["errors"]:
                print(f"    - 错误: {r['errors']}")
    
    # 保存结果到JSON
    output_path = OUTPUT_DIR / f"{datetime.now().strftime('%Y-%m-%d')}-data-check.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump({
            "check_time": datetime.now().isoformat(),
            "summary": {
                "total_files": len(csv_files),
                "total_nulls": total_nulls,
                "files_with_gaps": files_with_gaps,
                "files_with_jumps": files_with_jumps,
                "latest_date": latest_date.strftime('%Y-%m-%d') if latest_date else None
            },
            "details": all_results
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n详细结果已保存到: {output_path}")
    return all_results

if __name__ == "__main__":
    main()
