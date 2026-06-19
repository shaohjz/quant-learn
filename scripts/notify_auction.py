#!/usr/bin/env python3
"""
集合竞价快报（9:24）— 纯代码脚本

功能：
  1. 读取当日关注池（watchlist）的集合竞价数据
  2. 格式化快报内容
  3. 调用企微 Webhook 推送

数据源：
  - data/auction_data.json（由数据抓取脚本生成）
  - 或实时调用行情接口

依赖：
  - requests
  - scripts/wecom_notifier.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.wecom_notifier import send_markdown


def format_auction_report(data: dict) -> str:
    """格式化集合竞价快报"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    lines = [
        f"## 🔔 集合竞价快报 | {now}\n"
    ]
    
    if not data or not data.get("stocks"):
        lines.append("（今日无集合竞价数据）")
        return "\n".join(lines)
    
    # 按涨跌幅排序
    stocks = sorted(data["stocks"], key=lambda x: x.get("change_pct", 0), reverse=True)
    
    for stock in stocks[:10]:  # 只显示前 10 个
        name = stock.get("name", "未知")
        code = stock.get("code", "000000")
        price = stock.get("price", 0)
        change_pct = stock.get("change_pct", 0)
        
        emoji = "📈" if change_pct > 0 else "📉" if change_pct < 0 else "➡️"
        color = "🟢" if change_pct > 0 else "🔴" if change_pct < 0 else "⚪"
        
        lines.append(f"{emoji} **{name}**({code})")
        lines.append(f"  集合竞价：¥{price:.2f} {color} {change_pct:+.2f}%")
        
        # 显示触发的条件（如果有）
        triggers = stock.get("triggers", [])
        if triggers:
            lines.append(f"  > {' | '.join(triggers)}")
    
    return "\n".join(lines)


def main():
    """主函数"""
    # 读取集合竞价数据
    data_file = Path(__file__).parent.parent / "data" / "auction_data.json"
    
    if not data_file.exists():
        # 没有数据文件，发送简单通知
        send_markdown(f"## 🔔 集合竞价快报\n\n（未获取到集合竞价数据，请检查数据抓取脚本）")
        return
    
    try:
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ 读取数据文件失败：{e}")
        return
    
    # 格式化并发送
    report = format_auction_report(data)
    send_markdown(report)


if __name__ == "__main__":
    main()
