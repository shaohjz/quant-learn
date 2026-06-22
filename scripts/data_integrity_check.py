#!/usr/bin/env python3
"""
数据完整性检查脚本
检查行情数据完整性、入库时效性、数据质量
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import glob
from pathlib import Path

def check_data_integrity():
    """检查数据完整性"""
    print("=" * 60)
    print("开始数据完整性检查")
    print("=" * 60)
    
    # 项目根目录
    project_root = Path("C:/Users/Administrator/.openclaw/workspace/quant-learn")
    data_dir = project_root / "data"
    
    # 获取所有CSV文件
    csv_files = list(data_dir.glob("*.csv"))
    
    if not csv_files:
        print("❌ 没有找到CSV数据文件")
        return {}
    
    print(f"📊 找到 {len(csv_files)} 个CSV数据文件")
    
    # 检查结果
    results = {
        "total_files": len(csv_files),
        "missing_data": [],
        "data_gaps": [],
        "abnormal_values": [],
        "timeliness_issues": [],
        "files_checked": []
    }
    
    # 检查每个文件
    for csv_file in csv_files[:10]:  # 先检查前10个文件作为样本
        print(f"\n检查文件: {csv_file.name}")
        
        try:
            # 读取CSV文件
            df = pd.read_csv(csv_file)
            
            # 检查必要的列
            required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                print(f"  ❌ 缺少必要的列: {missing_columns}")
                results["missing_data"].append({
                    "file": csv_file.name,
                    "issue": f"缺少列: {missing_columns}"
                })
                continue
            
            # 转换日期列
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            # 检查数据完整性
            file_issues = check_file_integrity(df, csv_file.name)
            results["files_checked"].append({
                "file": csv_file.name,
                "records": len(df),
                "date_range": f"{df['date'].min().date()} 到 {df['date'].max().date()}",
                "issues": file_issues
            })
            
            # 汇总问题
            if file_issues.get("missing_dates"):
                results["missing_data"].extend([{
                    "file": csv_file.name,
                    "issue": f"缺失日期: {date}"
                } for date in file_issues["missing_dates"]])
            
            if file_issues.get("data_gaps"):
                results["data_gaps"].extend([{
                    "file": csv_file.name,
                    "issue": f"数据跳变: {gap}"
                } for gap in file_issues["data_gaps"]])
            
            if file_issues.get("abnormal_values"):
                results["abnormal_values"].extend([{
                    "file": csv_file.name,
                    "issue": f"异常值: {abnormal}"
                } for abnormal in file_issues["abnormal_values"]])
            
            # 检查时效性（最后数据日期是否在最近3天内）
            last_date = df['date'].max()
            days_since_last = (datetime.now() - last_date).days
            
            if days_since_last > 3:
                issue = f"数据时效性异常: 最后数据日期 {last_date.date()}, 距今 {days_since_last} 天"
                results["timeliness_issues"].append({
                    "file": csv_file.name,
                    "issue": issue
                })
                print(f"  ⚠️ {issue}")
            
            print(f"  ✅ 检查完成: {len(df)} 条记录, {df['date'].min().date()} 到 {df['date'].max().date()}")
            
        except Exception as e:
            print(f"  ❌ 检查文件时出错: {e}")
            results["missing_data"].append({
                "file": csv_file.name,
                "issue": f"文件读取错误: {e}"
            })
    
    return results

def check_file_integrity(df, filename):
    """检查单个文件的数据完整性"""
    issues = {
        "missing_dates": [],
        "data_gaps": [],
        "abnormal_values": []
    }
    
    # 检查日期连续性（交易日）
    date_series = df['date']
    date_diff = date_series.diff().dropna()
    
    # 检查是否有非交易日的跳变（简单检查：跳变超过7天可能是问题）
    large_gaps = date_diff[date_diff.dt.days > 7]
    if not large_gaps.empty:
        for idx, gap in large_gaps.items():
            issues["data_gaps"].append(f"日期跳变: {date_series.iloc[idx-1]} -> {date_series.iloc[idx]} ({gap.dt.days}天)")
    
    # 检查异常值
    # 1. 检查空值
    null_counts = df.isnull().sum()
    if null_counts.sum() > 0:
        for col in df.columns:
            if null_counts[col] > 0:
                issues["abnormal_values"].append(f"列 {col} 有 {null_counts[col]} 个空值")
    
    # 2. 检查价格异常（如价格为0或负数）
    price_columns = ['open', 'high', 'low', 'close']
    for col in price_columns:
        if col in df.columns:
            # 检查负值或零值
            invalid_prices = df[(df[col] <= 0) & (df[col].notna())]
            if not invalid_prices.empty:
                issues["abnormal_values"].append(f"列 {col} 有 {len(invalid_prices)} 个无效价格(≤0)")
            
            # 检查极端值（如价格变化超过50%）
            if len(df) > 1:
                price_change = df[col].pct_change().abs()
                extreme_changes = price_change[price_change > 0.5]
                if not extreme_changes.empty:
                    issues["abnormal_values"].append(f"列 {col} 有 {len(extreme_changes)} 个极端变化(>50%)")
    
    # 3. 检查成交量异常
    if 'volume' in df.columns:
        # 检查成交量为负或零
        invalid_volume = df[(df['volume'] < 0) & (df['volume'].notna())]
        if not invalid_volume.empty:
            issues["abnormal_values"].append(f"成交量有 {len(invalid_volume)} 个无效值(<0)")
    
    return issues

def generate_data_report(results):
    """生成数据检查报告"""
    report = "# 数据完整性检查报告\n\n"
    report += f"**检查时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    # 总体统计
    report += "## 📊 总体统计\n\n"
    report += f"- **检查文件数**: {results['total_files']}\n"
    report += f"- **实际检查文件数**: {len(results['files_checked'])}\n"
    report += f"- **发现问题文件数**: {len(results['missing_data']) + len(results['data_gaps']) + len(results['abnormal_values'])}\n\n"
    
    # 详细检查结果
    if results['missing_data']:
        report += "## ❌ 数据缺失问题\n\n"
        for issue in results['missing_data'][:10]:  # 只显示前10个
            report += f"- **{issue['file']}**: {issue['issue']}\n"
        if len(results['missing_data']) > 10:
            report += f"\n... 还有 {len(results['missing_data']) - 10} 个问题未显示\n"
        report += "\n"
    
    if results['data_gaps']:
        report += "## ⚠️ 数据跳变问题\n\n"
        for issue in results['data_gaps'][:10]:
            report += f"- **{issue['file']}**: {issue['issue']}\n"
        if len(results['data_gaps']) > 10:
            report += f"\n... 还有 {len(results['data_gaps']) - 10} 个问题未显示\n"
        report += "\n"
    
    if results['abnormal_values']:
        report += "## 🔍 数据质量问题\n\n"
        for issue in results['abnormal_values'][:10]:
            report += f"- **{issue['file']}**: {issue['issue']}\n"
        if len(results['abnormal_values']) > 10:
            report += f"\n... 还有 {len(results['abnormal_values']) - 10} 个问题未显示\n"
        report += "\n"
    
    if results['timeliness_issues']:
        report += "## ⏰ 数据时效性问题\n\n"
        for issue in results['timeliness_issues']:
            report += f"- **{issue['file']}**: {issue['issue']}\n"
        report += "\n"
    
    # 检查的文件详情
    report += "## 📋 检查的文件详情\n\n"
    for file_info in results['files_checked']:
        report += f"### {file_info['file']}\n"
        report += f"- **记录数**: {file_info['records']}\n"
        report += f"- **日期范围**: {file_info['date_range']}\n"
        
        if file_info['issues'].get('missing_dates'):
            report += f"- **缺失日期**: {len(file_info['issues']['missing_dates'])} 个\n"
        
        if file_info['issues'].get('data_gaps'):
            report += f"- **数据跳变**: {len(file_info['issues']['data_gaps'])} 个\n"
        
        if file_info['issues'].get('abnormal_values'):
            report += f"- **异常值**: {len(file_info['issues']['abnormal_values'])} 个\n"
        
        report += "\n"
    
    # 建议
    report += "## 💡 建议\n\n"
    
    if results['missing_data'] or results['data_gaps']:
        report += "1. **数据补全**: 需要重新拉取缺失的数据\n"
    
    if results['abnormal_values']:
        report += "2. **数据清洗**: 需要处理异常值和空值\n"
    
    if results['timeliness_issues']:
        report += "3. **时效性检查**: 需要检查数据入库流程\n"
    
    if not any([results['missing_data'], results['data_gaps'], results['abnormal_values'], results['timeliness_issues']]):
        report += "✅ **数据质量良好**，无需特殊处理\n"
    
    return report

def main():
    """主函数"""
    print("开始执行数据完整性检查...")
    
    # 检查数据完整性
    results = check_data_integrity()
    
    # 生成报告
    report = generate_data_report(results)
    
    # 保存报告
    report_dir = Path("C:/Users/Administrator/.openclaw/workspace/quant-learn/pm/data")
    report_dir.mkdir(parents=True, exist_ok=True)
    
    report_file = report_dir / f"{datetime.now().strftime('%Y-%m-%d')}-data.md"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n📝 报告已保存到: {report_file}")
    print("\n" + "=" * 60)
    print("数据完整性检查完成")
    print("=" * 60)
    
    return results

if __name__ == "__main__":
    results = main()
    
    # 输出总结
    print(f"\n总结:")
    print(f"  检查文件: {results['total_files']} 个")
    print(f"  发现问题: {len(results['missing_data']) + len(results['data_gaps']) + len(results['abnormal_values'])} 个")
    
    if results['timeliness_issues']:
        print(f"  时效性问题: {len(results['timeliness_issues'])} 个")
    
    # 返回状态码
    if any([results['missing_data'], results['data_gaps'], results['abnormal_values']]):
        exit(1)  # 有问题
    else:
        exit(0)  # 无问题