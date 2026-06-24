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
import requests
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.signal_generator import generate_signals
from sim.notifier import send_markdown
from sim.stock_pool import StockPool
from sim.realtime_price import get_latest_prices
from sim.config import get as cfg_get


def _check_network(timeout: int = 3) -> bool:
    """检测是否能访问外网（用 baostock 官网做探针）"""
    try:
        # 用 baostock 的登录接口做网络检测
        import baostock as bs
        lg = bs.login()
        ok = lg.error_code == "0"
        bs.logout()
        return ok
    except Exception:
        return False


def build_morning_brief() -> str:
    """生成多策略简报 Markdown"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"## 🌅 多策略简报 {today}")
    lines.append("")

    # 获取股票池
    pool = StockPool()
    all_stocks = pool.get_all()
    
    if not all_stocks:
        lines.append("（股票池为空，请检查 config.yaml 中的 stock_pool 配置）")
        return "\n".join(lines)

    # 检测网络
    network_ok = _check_network()
    if not network_ok:
        lines.append(f"股票池共 **{len(all_stocks)}** 只股票")
        lines.append("")
        lines.append("⚠️ 行情数据源不可达，暂无法生成实时信号")
        lines.append("")
        lines.append("可能原因：")
        lines.append("- 服务器在内网环境，无法访问外部股票数据API")
        lines.append("- baostock / 新浪行情 连接异常")
        lines.append("")
        lines.append("请稍后在可联网环境中重新运行，或配置内网行情数据代理。")
        lines.append("")
        lines.append("*数据来源：实时行情接口（需外网）*")
        return "\n".join(lines)

    # 为股票池中的每只股票生成信号
    signals = []
    for stock_code, stock_name in all_stocks.items():
        try:
            signal = generate_signals(stock_code, stock_name)
            signals.append(signal)
        except Exception as e:
            print(f"生成 {stock_code}({stock_name}) 信号时出错: {e}")
            continue

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
