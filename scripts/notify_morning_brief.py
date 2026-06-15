#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_morning_brief.py — 多策略简报（9:25 开盘前）

汇总当日买入/卖出信号，推送多策略简报到企微群。

用法：
    cd C:/Users/Administrator/.openclaw/workspace/quant-learn
    python scripts/notify_morning_brief.py
"""

import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.signal_generator import generate_signals
from sim.notifier import send_markdown
from sim.stock_pool import StockPool
from sim.config import get as cfg_get


def build_morning_brief() -> str:
    """生成多策略简报 Markdown"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"## 🌅 多策略简报 {today}")
    lines.append("")

    # 遍历股票池，逐只生成信号
    try:
        pool = StockPool()
        signals = []
        for code, name in pool.get_all().items():
            try:
                result = generate_signals(code, name)
                signals.append(result)
            except Exception as e:
                print(f"  ⚠️ {code}({name}) 信号生成异常: {e}")
    except Exception as e:
        return f"⚠️ **多策略简报** {today}\n\n信号生成失败：{e}"

    if not signals:
        lines.append("（今日无策略信号）")
        return "\n".join(lines)

    buy_signals = [s for s in signals if s.get("signal") == "BUY"]
    sell_signals = [s for s in signals if s.get("signal") == "SELL"]
    hold_signals = [s for s in signals if s.get("signal") == "HOLD"]

    if buy_signals:
        lines.append(f"**🟢 买入信号 {len(buy_signals)} 只**")
        for s in buy_signals:
            name = s.get("name", s.get("code", ""))
            code = s.get("code", "")
            price = s.get("price", 0)
            reasons = "，".join(s.get("reasons", [])) if s.get("reasons") else "—"
            lines.append(f"- **{name}**({code}) 参考价 ¥{price:.2f}")
            lines.append(f"  > {reasons}")
        lines.append("")

    if sell_signals:
        lines.append(f"**🔴 卖出信号 {len(sell_signals)} 只**")
        for s in sell_signals:
            name = s.get("name", s.get("code", ""))
            code = s.get("code", "")
            price = s.get("price", 0)
            reasons = "，".join(s.get("reasons", [])) if s.get("reasons") else "—"
            lines.append(f"- **{name}**({code}) 参考价 ¥{price:.2f}")
            lines.append(f"  > {reasons}")
        lines.append("")

    if hold_signals:
        lines.append(f"（观察池 {len(hold_signals)} 只持币观望）")

    lines.append("")
    lines.append("*开盘后以实时价为准，信号仅供参考*")
    return "\n".join(lines)


def main():
    content = build_morning_brief()
    print("推送内容：")
    print(content)
    print()
    ok = send_markdown(content)
    if ok:
        print("✅ 多策略简报推送成功")
    else:
        print("❌ 推送失败，请检查 webhook 配置")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
