#!/usr/bin/env python3
"""
收盘复盘通知（15:10）— 纯代码脚本

功能：
  1. 读取当日复盘报告（output/reviews/YYYY-MM-DD.md）
  2. 提取关键信息（信号、持仓变化、收益）
  3. 调用企微 Webhook 推送摘要

数据源：
  - output/reviews/YYYY-MM-DD.md
  - data/sim_live_mirror.db（模拟盘成交）
  - data/real_portfolio.db（实盘持仓）
"""

import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.wecom_notifier import send_markdown


def extract_summary(report_path: Path) -> str:
    """从复盘报告中提取摘要"""
    if not report_path.exists():
        return f"## 📊 收盘复盘 | {datetime.now().date()}\n\n（未找到复盘报告）"
    
    with open(report_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取关键信息
    lines = content.split('\n')
    
    # 构建摘要
    summary_lines = [
        f"## 📊 收盘复盘 | {datetime.now().date()}\n"
    ]
    
    # 提取模拟盘表现
    sim_match = re.search(r'模拟盘.*?总资产.*?¥([\d,.]+)', content, re.DOTALL)
    if sim_match:
        sim_value = sim_match.group(1)
        summary_lines.append(f"**模拟盘**：¥{sim_value}")
    
    # 提取实盘表现
    real_match = re.search(r'实盘.*?总资产.*?¥([\d,.]+)', content, re.DOTALL)
    if real_match:
        real_value = real_match.group(1)
        summary_lines.append(f"**实盘**：¥{real_value}")
    
    # 提取今日信号
    signals = re.findall(r'【(BUY|SELL|HOLD)】.*?(\d{6}).*?([\u4e00-\u9fa5]+)', content)
    if signals:
        summary_lines.append("\n**今日信号**：")
        for signal in signals[:5]:  # 最多显示5个
            side, code, name = signal
            emoji = "🟢" if side == "BUY" else "🔴" if side == "SELL" else "⚪"
            summary_lines.append(f"{emoji} {name}({code}) — {side}")
    
    # 提取持仓变化
    position_match = re.search(r'持仓变化.*?\n(.*?)(?=\n##|$)', content, re.DOTALL)
    if position_match:
        changes = position_match.group(1).strip()
        if changes:
            summary_lines.append(f"\n**持仓变化**：\n{changes[:200]}")  # 限制长度
    
    # 如果提取不到关键信息，发送简化版
    if len(summary_lines) <= 2:
        # 直接读取报告前500字符
        with open(report_path, 'r', encoding='utf-8') as f:
            preview = f.read(500)
        summary_lines.append("\n**报告预览**：")
        summary_lines.append(preview)
    
    return "\n".join(summary_lines)


def main():
    """主函数"""
    # 确定复盘报告路径
    today = datetime.now().date()
    report_path = Path(__file__).parent.parent / "output" / "reviews" / f"{today}.md"
    
    # 如果今日报告不存在，尝试找最近的报告
    if not report_path.exists():
        reports_dir = Path(__file__).parent.parent / "output" / "reviews"
        if reports_dir.exists():
            reports = sorted(reports_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
            if reports:
                report_path = reports[0]
    
    # 提取摘要并发送
    summary = extract_summary(report_path)
    send_markdown(summary)


if __name__ == "__main__":
    main()
