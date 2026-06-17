"""
run_daily_signals.py — 每日盘后自动化信号采集

定时任务：
  1. 15:05（收盘后）→ 采集当日信号并生成报告
  2. 09:05（开盘前）→ 检查解禁预警等盘前信息

输出：output/daily_signals/YYYY-MM-DD_report.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime

# 确保能找到 a_stock_data_signals
# 脚本在 skills/a-stock-data-signals/ 下
# 需要找到 workspace 根目录
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from a_stock_data_signals import (
    multi_signal_report,
    hot_stocks_signal,
    northbound_signal,
    daily_dragon_tiger_signal,
    industry_rotation_signal,
)


def save_report(report: dict, subdir: str = "daily_signals"):
    """保存报告到 output 目录"""
    out_dir = ROOT / "output" / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = report.get("date", datetime.now().strftime("%Y-%m-%d"))
    path = out_dir / f"{date_str}_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return path


def format_report_text(report: dict) -> str:
    """将报告格式化为可读文本"""
    lines = []
    lines.append(f"📊 量化信号日报 — {report.get('date', '未知')}")
    lines.append("=" * 50)

    # 强势股题材
    hs = report.get("hot_stocks", {})
    if hs.get("stocks"):
        lines.append(f"\n🔥 当日强势股（共{hs['total']}只）")
        tags_str = ' | '.join(f'{t["tag"]}({t["count"]})' for t in hs.get('top_tags', [])[:8])
        lines.append(f"   题材热度: {tags_str}")
        lines.append(f"   涨幅前5:")
        for s in sorted(hs["stocks"], key=lambda x: x["change_pct"], reverse=True)[:5]:
            lines.append(f"     {s['code']} {s['name']}: {s['change_pct']:+.2f}% | {s.get('reason', '')}")
    else:
        lines.append(f"\n🔥 强势股: 无数据")

    # 北向资金
    nb = report.get("northbound", {})
    if nb.get("data_points", 0) > 0:
        lines.append(f"\n💰 北向资金: {nb.get('direction', 'N/A')}")
        lines.append(f"   沪股通: {nb.get('hgt_total', 0):+.2f}亿 | 深股通: {nb.get('sgt_total', 0):+.2f}亿 | 合计: {nb.get('hgt_sgt_total', 0):+.2f}亿")
    else:
        lines.append(f"\n💰 北向资金: 无数据")

    # 龙虎榜
    dt = report.get("dragon_tiger", {})
    if dt.get("stocks"):
        lines.append(f"\n🐉 龙虎榜（净买>3000万，共{dt['total']}只）")
        for s in dt["stocks"][:8]:
            lines.append(f"   {s['code']} {s['name']}: 净买{s['net_buy_wan']}万 | {s.get('reason', '')}")
    else:
        lines.append(f"\n🐉 龙虎榜: 无数据")

    # 行业轮动
    ind = report.get("industry", {})
    if ind.get("hot_sectors"):
        lines.append(f"\n🏭 题材热度 TOP10:")
        for tag in ind["hot_sectors"][:10]:
            lines.append(f"   {tag}")
    if ind.get("indices"):
        lines.append(f"\n📈 主要指数:")
        for idx in ind["indices"]:
            lines.append(f"   {idx['name']}: {idx['change_pct']:+.2f}%")

    lines.append(f"\n{'=' * 50}")
    lines.append(f"生成时间: {report.get('timestamp', '')}")

    return "\n".join(lines)


def run_daily_report():
    """运行每日盘后报告"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始采集信号...")

    report = multi_signal_report()

    # 保存 JSON
    path = save_report(report)
    print(f"[OK] 报告已保存: {path}")

    # 输出文本
    text = format_report_text(report)
    print("\n" + text)

    return report, text


def run_morning_check():
    """开盘前检查"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 盘前检查...")

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "type": "morning_check",
    }

    # 北向资金（前一日收盘）
    try:
        report["northbound"] = northbound_signal()
    except Exception as e:
        report["northbound"] = {"error": str(e)}

    # 行业轮动
    try:
        report["industry"] = industry_rotation_signal(top_n=10)
    except Exception as e:
        report["industry"] = {"error": str(e)}

    path = save_report(report, subdir="daily_signals")
    print(f"[OK] 盘前检查已保存: {path}")

    return report


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"

    if mode == "morning":
        run_morning_check()
    elif mode == "daily":
        run_daily_report()
    else:
        print(f"用法: python {__file__} [daily|morning]")
        print("  daily   - 盘后报告（默认）")
        print("  morning - 盘前检查")
