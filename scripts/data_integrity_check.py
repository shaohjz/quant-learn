#!/usr/bin/env python3
"""
数据完整性检查脚本
检查行情数据完整性、入库时效性、数据质量
"""

import os
import json
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# 配置
DATA_DIR = Path(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data")
PM_DATA_DIR = Path(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\pm\data")
TODAY = datetime.now().strftime("%Y-%m-%d")
TODAY_TRADE = datetime.now().strftime("%Y%m%d")

def get_latest_trade_date():
    """获取最新交易日"""
    trade_dates_file = DATA_DIR / "trade_dates.json"
    if trade_dates_file.exists():
        with open(trade_dates_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            dates = data.get('dates', [])
            if dates:
                return dates[-1]  # 返回最后一个日期
    return TODAY_TRADE

def check_csv_integrity(csv_file):
    """检查单个CSV文件的数据完整性"""
    issues = []
    
    try:
        df = pd.read_csv(csv_file)
        
        # 检查必要的列
        required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            issues.append(f"缺少列: {missing_columns}")
        
        # 检查空值
        null_counts = df.isnull().sum()
        if null_counts.sum() > 0:
            for col, count in null_counts.items():
                if count > 0:
                    issues.append(f"列 '{col}' 有 {count} 个空值")
        
        # 检查日期连续性（使用交易日历）
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        # 加载交易日历
        trade_dates_file = DATA_DIR / "trade_dates.json"
        if trade_dates_file.exists():
            with open(trade_dates_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                trade_dates = set(data.get('dates', []))
                
                # 只检查数据文件日期范围内的交易日
                data_start = df['date'].min().strftime('%Y-%m-%d')
                data_end = df['date'].max().strftime('%Y-%m-%d')
                
                # 筛选在数据日期范围内的交易日
                relevant_trade_dates = {d for d in trade_dates if data_start <= d <= data_end}
                df_dates = set(df['date'].dt.strftime('%Y-%m-%d'))
                
                missing_trade_dates = relevant_trade_dates - df_dates
                
                # 只报告最近30天内的缺失（相对于数据最新日期）
                latest_date = df['date'].max()
                recent_threshold = latest_date - timedelta(days=30)
                recent_missing = [d for d in missing_trade_dates 
                                if datetime.strptime(d, '%Y-%m-%d') >= recent_threshold]
                
                if recent_missing:
                    issues.append(f"最近30天缺少 {len(recent_missing)} 个交易日数据")
        else:
            # 如果没有交易日历，使用简单的间隔检查
            date_diffs = df['date'].diff().dropna()
            if len(date_diffs) > 0:
                non_business_day_gaps = date_diffs[date_diffs > pd.Timedelta(days=7)]
                if len(non_business_day_gaps) > 0:
                    issues.append(f"发现 {len(non_business_day_gaps)} 处日期间隔>7天（可能缺数据）")
        
        # 检查异常值
        # 检查价格为0或负数
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                invalid_prices = df[df[col] <= 0]
                if len(invalid_prices) > 0:
                    issues.append(f"列 '{col}' 有 {len(invalid_prices)} 条无效价格（<=0）")
        
        # 检查成交量异常
        if 'volume' in df.columns:
            invalid_volume = df[df['volume'] < 0]
            if len(invalid_volume) > 0:
                issues.append(f"成交量有 {len(invalid_volume)} 条无效数据（<0）")
        
        # 检查高低价关系
        if all(col in df.columns for col in ['high', 'low', 'open', 'close']):
            invalid_hl = df[df['high'] < df['low']]
            if len(invalid_hl) > 0:
                issues.append(f"高低价关系异常：{len(invalid_hl)} 条数据 high < low")
            
            # 检查开盘/收盘价是否在高低价范围内
            invalid_range = df[(df['open'] < df['low']) | (df['open'] > df['high']) |
                             (df['close'] < df['low']) | (df['close'] > df['high'])]
            if len(invalid_range) > 0:
                issues.append(f"开/收盘价超出高低价范围：{len(invalid_range)} 条")
        
        return {
            'file': csv_file.name,
            'total_rows': len(df),
            'date_range': f"{df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}",
            'latest_date': df['date'].max().strftime('%Y-%m-%d'),
            'issues': issues,
            'status': 'OK' if not issues else 'ISSUES'
        }
        
    except Exception as e:
        return {
            'file': csv_file.name,
            'error': str(e),
            'status': 'ERROR'
        }

def check_data_freshness(csv_files):
    """检查数据入库时效性"""
    freshness_issues = []
    latest_trade_date = get_latest_trade_date()
    
    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            df['date'] = pd.to_datetime(df['date'])
            latest_data_date = df['date'].max()
            
            # 转换为字符串比较
            latest_data_str = latest_data_date.strftime('%Y%m%d')
            
            # 如果最新数据日期早于最新交易日，说明可能缺数据
            if latest_trade_date and latest_data_str < latest_trade_date:
                # 检查是否是非交易日
                trade_dates_file = DATA_DIR / "trade_dates.json"
                if trade_dates_file.exists():
                    with open(trade_dates_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        trade_dates = data.get('dates', [])
                        
                        # 如果最新交易日不在交易日期列表中，说明可能是非交易日
                        if latest_trade_date not in trade_dates:
                            # 找到最新的交易日
                            trade_dates_sorted = sorted(trade_dates)
                            latest_valid_trade = None
                            for d in reversed(trade_dates_sorted):
                                if d <= latest_data_str:
                                    latest_valid_trade = d
                                    break
                            
                            if latest_valid_trade and latest_data_str == latest_valid_trade:
                                continue  # 数据是最新的
                        
            # 检查文件修改时间
            file_mtime = datetime.fromtimestamp(csv_file.stat().st_mtime)
            time_diff = datetime.now() - file_mtime
            
            if time_diff > timedelta(hours=24):
                freshness_issues.append({
                    'file': csv_file.name,
                    'last_update': file_mtime.strftime('%Y-%m-%d %H:%M:%S'),
                    'age_hours': round(time_diff.total_seconds() / 3600, 1)
                })
                
        except Exception as e:
            freshness_issues.append({
                'file': csv_file.name,
                'error': str(e)
            })
    
    return freshness_issues

def main():
    """主函数"""
    print(f"开始数据完整性检查 - {TODAY}")
    
    # 获取所有CSV文件
    csv_files = list(DATA_DIR.glob("*.csv"))
    
    if not csv_files:
        print("未找到CSV数据文件")
        return
    
    print(f"找到 {len(csv_files)} 个CSV文件")
    
    # 检查数据完整性
    print("\n1. 检查数据完整性...")
    integrity_results = []
    all_issues = []
    
    for csv_file in csv_files:
        result = check_csv_integrity(csv_file)
        integrity_results.append(result)
        
        if result['status'] != 'OK':
            all_issues.append(result)
            print(f"  ❌ {result['file']}: {result.get('issues', result.get('error', 'Unknown'))}")
        else:
            print(f"  ✅ {result['file']}: OK ({result['total_rows']} 行)")
    
    # 检查入库时效性
    print("\n2. 检查入库时效性...")
    freshness_issues = check_data_freshness(csv_files)
    
    if freshness_issues:
        print(f"  发现 {len(freshness_issues)} 个时效性问题:")
        for issue in freshness_issues:
            if 'error' in issue:
                print(f"    ❌ {issue['file']}: {issue['error']}")
            else:
                print(f"    ⚠️  {issue['file']}: 最后更新 {issue['last_update']} ({issue['age_hours']} 小时前)")
    else:
        print("  ✅ 所有数据都是最新的")
    
    # 生成报告
    print("\n3. 生成数据日报...")
    
    # 确保输出目录存在
    PM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    report_file = PM_DATA_DIR / f"{TODAY}-data.md"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"# 📊 数据完整性日报 {TODAY}\n\n")
        
        f.write("## 📈 概要\n\n")
        f.write(f"- 检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"- 数据文件总数: {len(csv_files)}\n")
        f.write(f"- 数据完整: {len([r for r in integrity_results if r['status'] == 'OK'])} \n")
        f.write(f"- 存在问题: {len(all_issues)}\n")
        f.write(f"- 时效性问题: {len(freshness_issues)}\n\n")
        
        f.write("## ✅ 数据完整性检查\n\n")
        
        if all_issues:
            f.write("### 发现的问题\n\n")
            for issue in all_issues:
                f.write(f"#### {issue['file']}\n\n")
                if issue['status'] == 'ERROR':
                    f.write(f"**错误**: {issue['error']}\n\n")
                else:
                    f.write("**问题详情**:\n")
                    for prob in issue['issues']:
                        f.write(f"- {prob}\n")
                    f.write("\n")
        else:
            f.write("✅ 所有数据文件完整性检查通过\n\n")
        
        f.write("## ⏰ 入库时效性检查\n\n")
        
        if freshness_issues:
            f.write("### 时效性问题\n\n")
            for issue in freshness_issues:
                f.write(f"- **{issue['file']}**: ")
                if 'error' in issue:
                    f.write(f"错误 - {issue['error']}\n")
                else:
                    f.write(f"最后更新 {issue['last_update']} ({issue['age_hours']} 小时前)\n")
            f.write("\n")
        else:
            f.write("✅ 所有数据都是最新的\n\n")
        
        f.write("## 📋 详细检查结果\n\n")
        f.write("| 文件 | 总行数 | 日期范围 | 最新日期 | 状态 |\n")
        f.write("|------|--------|----------|----------|------|\n")
        
        for result in integrity_results:
            status_icon = "✅" if result['status'] == 'OK' else "❌"
            if result['status'] == 'OK':
                f.write(f"| {result['file']} | {result['total_rows']} | {result['date_range']} | {result['latest_date']} | {status_icon} |\n")
            else:
                f.write(f"| {result['file']} | - | - | - | {status_icon} |\n")
        
        f.write("\n---\n")
        f.write(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
    
    print(f"\n✅ 数据日报已生成: {report_file}")
    
    # 如果有问题，输出汇总
    if all_issues or freshness_issues:
        print("\n⚠️  发现问题汇总:")
        if all_issues:
            print(f"  - 数据完整性问题: {len(all_issues)} 个文件")
        if freshness_issues:
            print(f"  - 时效性问题: {len(freshness_issues)} 个文件")
        print("\n请查看报告详情并进行修复")
    else:
        print("\n🎉 所有检查通过！数据质量良好")

if __name__ == "__main__":
    main()
