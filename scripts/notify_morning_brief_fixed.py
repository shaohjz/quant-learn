#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_morning_brief_fixed.py — 多策略简报（修复版）

汇总当日买入/卖出信号，推送多策略简报到企微群。
- 增加错误处理和详细日志
- 使用多线程并发获取信号，提高效率
- 单个股票处理失败不影响整体

用法：
    cd C:/Users/Administrator/.openclaw/workspace/quant-learn
    python scripts/notify_morning_brief_fixed.py
"""

import sys
import traceback
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.signal_generator import generate_signals
from sim.notifier import send_markdown
from sim.stock_pool import StockPool
from sim.config import get as cfg_get

# 配置
MAX_WORKERS = 5  # 并发线程数
TIMEOUT_PER_STOCK = 30  # 每只股票超时时间（秒）
OVERALL_TIMEOUT = 180  # 整体超时（秒）


def generate_signal_safe(stock_code: str, stock_name: str) -> dict:
    """安全生成信号（带异常处理）"""
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(generate_signals, stock_code, stock_name)
            result = future.result(timeout=TIMEOUT_PER_STOCK)
            return result
    except FutureTimeout:
        print(f"    ⏱️ 超时（{TIMEOUT_PER_STOCK}秒）", flush=True)
        return {
            "code": stock_code, 
            "name": stock_name, 
            "signal": "HOLD", 
            "price": 0,
            "reasons": [f"⚠️ 数据获取超时"]
        }
    except Exception as e:
        print(f"    ❌ 错误: {e}", flush=True)
        return {
            "code": stock_code, 
            "name": stock_name, 
            "signal": "HOLD", 
            "price": 0,
            "reasons": [f"⚠️ 生成信号失败: {str(e)[:50]}"]
        }


def build_morning_brief() -> str:
    """生成多策略简报 Markdown"""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = []
    lines.append(f"## 🌅 多策略简报 {today}")
    lines.append("")

    # 获取股票池
    print("📋 获取股票池...", flush=True)
    pool = StockPool()
    all_stocks = pool.get_all()
    
    if not all_stocks:
        lines.append("（股票池为空，请检查 config.yaml 中的 stock_pool 配置）")
        return "\n".join(lines)

    print(f"✅ 股票池获取成功，共 {len(all_stocks)} 只股票\n", flush=True)

    # 并发生成信号
    signals = []
    total = len(all_stocks)
    
    print(f"🚀 开始并发生成信号（线程数: {MAX_WORKERS}，单股超时: {TIMEOUT_PER_STOCK}秒）\n", flush=True)
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 提交所有任务
        future_to_stock = {
            executor.submit(generate_signal_safe, code, name): (code, name)
            for code, name in all_stocks.items()
        }
        
        # 收集结果
        completed = 0
        for future in as_completed(future_to_stock, timeout=OVERALL_TIMEOUT):
            code, name = future_to_stock[future]
            completed += 1
            
            try:
                signal_obj = future.result()
                signals.append(signal_obj)
                signal_type = signal_obj.get("signal", "UNKNOWN")
                price = signal_obj.get("price", 0)
                print(f"[{completed}/{total}] ✅ {code}({name}) -> {signal_type} ¥{price:.2f}", flush=True)
            except Exception as e:
                print(f"[{completed}/{total}] ❌ {code}({name}) -> 错误: {e}", flush=True)
                signals.append({
                    "code": code,
                    "name": name,
                    "signal": "HOLD",
                    "price": 0,
                    "reasons": [f"处理失败: {str(e)[:50]}"]
                })

    print(f"\n✅ 信号生成完成，成功 {len(signals)}/{total}\n", flush=True)

    if not signals:
        lines.append("（今日无策略信号）")
        return "\n".join(lines)

    # 分类统计
    buy_signals = [s for s in signals if s.get("signal") == "BUY"]
    sell_signals = [s for s in signals if s.get("signal") == "SELL"]
    hold_signals = [s for s in signals if s.get("signal") == "HOLD"]
    error_signals = [s for s in signals if s.get("signal") == "HOLD" and any("⚠️" in r for r in s.get("reasons", []))]

    # 生成简报内容
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
    
    if error_signals:
        lines.append(f"⚠️ {len(error_signals)} 只股票数据获取失败（已归入观察池）")

    lines.append("")
    lines.append("*开盘后以实时价为准，信号仅供参考*")
    
    # 添加统计信息
    lines.append("")
    lines.append(f"---")
    lines.append(f"📊 统计：买入 {len(buy_signals)} | 卖出 {len(sell_signals)} | 观望 {len(hold_signals)} | 失败 {len(error_signals)}")
    
    return "\n".join(lines)


def main():
    start_time = datetime.now()
    print(f"⏰ 开始执行多策略简报生成 @ {start_time.strftime('%H:%M:%S')}")
    print(f"   配置：{MAX_WORKERS}线程 | 单股{TIMEOUT_PER_STOCK}秒 | 整体{OVERALL_TIMEOUT}秒\n", flush=True)
    
    try:
        content = build_morning_brief()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        print("=" * 60)
        print("📄 推送内容：")
        print(content)
        print("=" * 60)
        print(f"\n⏱️ 总耗时: {duration:.1f} 秒\n")
        
        # 推送到企微
        print("🚀 开始推送到企微群...", flush=True)
        ok = send_markdown(content)
        if ok:
            print("✅ 多策略简报推送成功")
            return 0
        else:
            print("❌ 推送失败，请检查 webhook 配置")
            return 1
        
    except Exception as e:
        print(f"\n❌ 发生未预期错误: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
