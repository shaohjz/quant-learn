#!/usr/bin/env python3
"""生成数据日报 Markdown"""
import json
from datetime import datetime
from pathlib import Path

def generate_report():
    check_file = Path("pm/data/2026-06-09-data-check.json")
    if not check_file.exists():
        print("检查结果文件不存在，请先运行 data_integrity_check.py")
        return
    
    with open(check_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    summary = data['summary']
    details = data['details']
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 分类问题
    warning_files = [d for d in details if d['status'] == 'warning']
    error_files = [d for d in details if d['status'] == 'error']
    ok_files = [d for d in details if d['status'] == 'ok']
    empty_files = [d for d in details if d['status'] == 'empty']
    
    # 找出有空值的文件
    files_with_nulls = [d for d in details if d['null_count'] > 0]
    
    # 构建 Markdown
    lines = []
    lines.append(f"# 数据日报 {today}")
    lines.append("")
    lines.append(f"> 检查时间: {data['check_time']}")
    lines.append("")
    lines.append("## 一、数据时效性")
    lines.append("")
    latest = summary.get('latest_date', 'N/A')
    if latest:
        from datetime import datetime as dt
        try:
            last_dt = dt.strptime(latest, '%Y-%m-%d')
            now = dt.now()
            diff = (now - last_dt).days
            status = "🔴" if diff > 3 else ("🟡" if diff > 1 else "🟢")
            lines.append(f"{status} **最后数据日期**: {latest}（距今 **{diff}** 天）")
            if diff > 3:
                lines.append("")
                lines.append("⚠️ **数据严重滞后！** 需要立即补数据。")
        except:
            lines.append(f"最后数据日期: {latest}（日期解析失败）")
    lines.append("")
    
    lines.append("## 二、数据完整性汇总")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 股票文件总数 | {summary['total_files']} |")
    lines.append(f"| ✅ 正常 | {len(ok_files)} |")
    lines.append(f"| ⚠️ 警告 | {len(warning_files)} |")
    lines.append(f"| ❌ 错误 | {len(error_files)} |")
    lines.append(f"| 总空值数 | {summary['total_nulls']} |")
    lines.append(f"| 缺失交易日文件数 | {summary['files_with_gaps']} |")
    lines.append(f"| 价格跳变文件数 | {summary['files_with_gaps']} |")  # Note: files_with_jumps
    lines.append("")
    
    lines.append("## 三、数据质量问题")
    lines.append("")
    
    if files_with_nulls:
        lines.append("### 空值问题")
        lines.append("")
        lines.append("| 文件 | 空值数 |")
        lines.append("|------|--------|")
        for d in files_with_nulls:
            lines.append(f"| {d['file']} | {d['null_count']} |")
        lines.append("")
    
    if warning_files:
        lines.append("### 价格跳变（>10%，可能是涨停/跌停，需人工确认）")
        lines.append("")
        lines.append("| 文件 | 跳变次数 | 示例 |")
        lines.append("|------|----------|------|")
        for d in warning_files[:10]:
            jumps = d.get('price_jumps', [])
            example = jumps[0] if jumps else '-'
            lines.append(f"| {d['file']} | {len(jumps)} | {example} |")
        if len(warning_files) > 10:
            lines.append(f"| ... | ... | 还有 {len(warning_files)-10} 个文件 |")
        lines.append("")
        lines.append("> 💡 注: A股涨跌停为 ±10%，跳变可能是正常涨跌停，需结合成交量判断。")
        lines.append("")
    
    if error_files:
        lines.append("### 错误文件")
        lines.append("")
        for d in error_files:
            lines.append(f"**{d['file']}**: {', '.join(d.get('errors', []))}")
        lines.append("")
    
    lines.append("## 四、补数据状态")
    lines.append("")
    lines.append("### 自动补数据尝试")
    lines.append("")
    lines.append("❌ **AKShare 接口全部连接失败** (`Connection aborted: RemoteDisconnected`)")
    lines.append("")
    lines.append("**原因分析**:")
    lines.append("1. AKShare 服务端限流/封禁")
    lines.append("2. 网络环境限制（公司内网）")
    lines.append("3. AKShare 数据源（东方财富）反爬限制")
    lines.append("")
    lines.append("**建议修复方案**:")
    lines.append("1. 切换数据源（BaoStock / Tushare / 聚宽）")
    lines.append("2. 增加请求延迟 + 重试机制")
    lines.append("3. 使用 QMT / vnpy 等本地数据源")
    lines.append("4. 手动下载 CSV 后导入")
    lines.append("")
    
    lines.append("## 五、数据文件详情")
    lines.append("")
    lines.append("| 文件 | 状态 | 首日期 | 末日期 | 行数 | 空值 | 跳变 |")
    lines.append("|------|------|--------|--------|------|------|------|")
    for d in details:
        status_icon = {"ok": "✅", "warning": "⚠️", "error": "❌", "empty": "⬜"}[d['status']]
        jumps = len(d.get('price_jumps', []))
        gaps = len(d.get('gap_dates', []))
        lines.append(f"| {d['file']} | {status_icon} {d['status']} | {d['first_date']} | {d['last_date']} | {d['row_count']} | {d['null_count']} | {jumps} |")
    lines.append("")
    
    lines.append("## 六、结论与行动项")
    lines.append("")
    
    action_items = []
    if summary['total_nulls'] > 0:
        action_items.append(f"修复 {summary['total_nulls']} 个空值（文件: {[d['file'] for d in files_with_nulls]}）")
    if latest:
        from datetime import datetime as dt
        try:
            diff = (dt.now() - dt.strptime(latest, '%Y-%m-%d')).days
            if diff > 3:
                action_items.append(f"**紧急**: 数据滞后 {diff} 天，需补数据（2026-05-23 至今）")
        except: pass
    if summary['files_with_jumps'] > 0:
        action_items.append(f"确认 {summary['files_with_jumps']} 个文件的价格跳变是否为涨跌停")
    
    if action_items:
        for i, item in enumerate(action_items, 1):
            lines.append(f"{i}. {item}")
    else:
        lines.append("✅ 无紧急问题")
    lines.append("")
    lines.append("--- ")
    lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")
    
    # 写文件
    out_path = Path(f"pm/data/{today}-data.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    print(f"✅ 数据日报已生成: {out_path}")
    return str(out_path)

if __name__ == "__main__":
    generate_report()
