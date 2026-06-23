#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_morning_brief_v2.py — 多策略简报（9:25 开盘前）v2

汇总当日买入/卖出信号，推送多策略简报到企微群。
增加错误处理、超时控制和调试信息。

用法：
    cd C:/Users/Administrator/.openclaw/workspace/quant-learn
    python scripts/notify_morning_brief_v2.py
"""

import sys
import signal
import traceback
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.signal_generator import generate_signals
from sim.notifier import send_markdown
from sim.stock_pool import StockPool
from sim.config import get as cfg_get

# 设置整体超时（秒）
OVERALL_TIMEOUT = 180  # 3分钟


def signal_handler(signum, frame):
    """超时处理函数"""
    print(f"\n⏱️ 整体执行超时（{OVERALL_TIMEOUT}秒），终止执行")
    sys.exit(1)


def generate_signal_with_timeout(stock_code: str, stock_name: str, timeout: int = 30) -> dict:
    """带超时的信号生成"""
    try:
        # 使用线程池来执行，这样可以设置超时
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(generate_signals, stock_code, stock_name)
            try:
                result = future.result(timeout=timeout)
                return result
            except FutureTimeout:
                print(f"    ⏱️ 超时（{timeout}秒）")
                return {"code": stock_code, "name": stock_name, "signal": "HOLD", "reasons": [f"数据获取超时（{timeout}秒）"]}
    except Exception as e:
        print(f"    ❌ 错误: {e}")
        return {"code": stock_code, "name": stock_name, "signal": "HOLD", "reasons": [f"生成信号时出错: {str(e)}"]}


def build_morning_brief() -> str:
    """生成多策略简报 Markdown"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"## 🌅 多策略简报 {today}")
    lines.append("")

    # 获取股票池
    print("📋 获取股票池...")
    pool = StockPool()
    all_stocks = pool.get_all()
    
    if not all_stocks:
        lines.append("（股票池为空，请检查 config.yaml 中的 stock_pool 配置）")
        return "\n".join(lines)

    print(f"✅ 股票池获取成功，共 {len(all_stocks)} 只股票\n")

    # 为股票池中的每只股票生成信号
    signals = []
    total = len(all_stocks)
    
    for idx, (stock_code, stock_name) in enumerate(all_stocks.items(), 1):
        print(f"[{idx}/{total}] 生成 {stock_code}({stock_name}) 信号...", end=" ", flush=True)
        try:
            signal_obj = generate_signal_with_timeout(stock_code, stock_name, timeout=30)
            signals.append(signal_obj)
            signal_type = signal_obj.get("signal", "UNKNOWN")
            print(f"✅ {signal_type}")
        except Exception as e:
            print(f"❌ 错误: {e}")
            traceback.print_exc()
            continue

    print(f"\n✅ 信号生成完成，成功 {len(signals)}/{total}\n")

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
    # 设置整体超时
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(OVERALL_TIMEOUT)
    
    try:
        print(f"⏰ 开始执行多策略简报生成（超时设置：{OVERALL_TIMEOUT}秒）\n")
        content = build_morning_brief()
        
        print("=" * 60)
        print("推送内容：")
        print(content)
        print("=" * 60)
        print()
        
        ok = send_markdown(content)
        if ok:
            print("✅ 多策略简报推送成功")
        else:
            print("❌ 推送失败，请检查 webhook 配置")
        
        signal.alarm(0)  # 取消超时
        return 0 if ok else 1
        
    except Exception as e:
        print(f"\n❌ 发生未预期错误: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
