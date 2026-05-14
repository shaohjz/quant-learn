#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_daily.py — A股模拟盘 每日主程序

用法:
  python run_daily.py --pre-market   盘前信号（只生成信号，不交易）
  python run_daily.py --settle       收盘结算（执行交易 + 结算 + 报告）
  python run_daily.py                默认：执行完整流程（信号→交易→结算→报告）
"""

import sys
import os
import argparse
from datetime import date as Date

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sim.db import init_tables
from sim.engine import SimEngine
from sim.signal_generator import generate_signals
from sim.stock_pool import StockPool
from sim.realtime_price import get_latest_prices
from sim.reporter import generate_daily_report, generate_nav_chart


def run_pre_market():
    """盘前模式：只生成信号"""
    print("=" * 50)
    print("🌅 盘前信号分析")
    print("=" * 50)

    pool = StockPool()
    engine = SimEngine()
    positions = engine.get_positions()
    pos_map = {p["stock_code"]: p for p in positions}

    signals = []
    for code, name in pool.get_all().items():
        existing = None
        if code in pos_map:
            p = pos_map[code]
            existing = {
                "quantity": p["quantity"],
                "avg_cost": float(p["avg_cost"]),
                "max_price_since_buy": float(p["current_price"]) if p["current_price"] else float(p["avg_cost"]),
            }

        sig = generate_signals(code, name, existing_position=existing)
        signals.append(sig)
        emoji = "🟢" if sig["signal"] == "BUY" else "🔴" if sig["signal"] == "SELL" else "⚪"
        print(f"\n{emoji} {name}({code}): {sig['signal']}")
        print(f"  原因: {', '.join(sig['reasons'])}")

    return signals


def run_settle(trade_date: Date = None):
    """收盘结算模式：执行交易 + 更新价格 + 结算 + 报告"""
    trade_date = trade_date or Date.today()
    print("=" * 50)
    print(f"🌆 收盘结算 ({trade_date})")
    print("=" * 50)

    pool = StockPool()
    engine = SimEngine()

    # 1. 获取最新价格
    codes = pool.get_codes()
    prices_data = get_latest_prices(codes)
    price_map = {c: d["price"] for c, d in prices_data.items() if d["price"] > 0}
    name_map = pool.get_all()

    # 补充名称（新浪可能返回名称）
    for c, d in prices_data.items():
        if d.get("name") and not name_map.get(c):
            name_map[c] = d["name"]

    print(f"\n📡 行情: {', '.join(f'{name_map.get(c,c)} ¥{p:.2f}' for c, p in price_map.items())}")

    # 2. 生成信号
    positions = engine.get_positions()
    pos_map = {p["stock_code"]: p for p in positions}

    signals = []
    for code, name in pool.get_all().items():
        existing = None
        if code in pos_map:
            p = pos_map[code]
            existing = {
                "quantity": p["quantity"],
                "avg_cost": float(p["avg_cost"]),
                "max_price_since_buy": float(p["current_price"]) if p["current_price"] else float(p["avg_cost"]),
            }

        sig = generate_signals(code, name, existing_position=existing)
        signals.append(sig)
        emoji = "🟢" if sig["signal"] == "BUY" else "🔴" if sig["signal"] == "SELL" else "⚪"
        print(f"\n{emoji} {name}({code}): {sig['signal']}")
        print(f"  原因: {', '.join(sig['reasons'])}")

    # 3. 执行交易
    for sig in signals:
        code = sig["code"]
        name = sig["name"]
        price = price_map.get(code, sig["price"])
        if price <= 0:
            continue

        if sig["signal"] == "BUY":
            # 风控：单次开仓不超过 60% 资金
            acct = engine.get_account()
            max_amount = acct["cash"] * 0.60
            quantity = int(max_amount / price)
            quantity = (quantity // 100) * 100
            if quantity > 0:
                result = engine.buy(
                    stock_code=code, price=price, quantity=quantity,
                    stock_name=name, signal_reason="+".join(sig["reasons"]),
                    trade_date=trade_date,
                )
                print(f"  → 执行买入: {result['msg']}")
            else:
                print(f"  → 买入信号但资金不足({code})")

        elif sig["signal"] == "SELL":
            pos = pos_map.get(code)
            if pos and pos["quantity"] > 0:
                result = engine.sell(
                    stock_code=code, price=price, quantity=pos["quantity"],
                    stock_name=name, signal_reason="+".join(sig["reasons"]),
                    trade_date=trade_date,
                )
                print(f"  → 执行卖出: {result['msg']}")
            else:
                print(f"  → 卖出信号但无持仓({code})")

    # 4. 更新持仓价格
    if price_map:
        engine.update_prices(price_map)
        print("\n  ✓ 持仓价格已更新")

    # 5. 每日结算
    settle = engine.daily_settle(trade_date)
    print(f"\n📊 结算: 总资产 ¥{settle['total_value']:,.2f}, "
          f"日收益 {settle['daily_return']*100:+.2f}%, "
          f"累计 {settle['cumulative_return']*100:+.2f}%")

    # 6. 生成报告
    report = generate_daily_report(trade_date, signals)
    print("\n" + report)

    # 7. 生成净值曲线
    try:
        chart_path = generate_nav_chart()
        if chart_path:
            print(f"\n📈 净值曲线已保存: {chart_path}")
    except Exception as e:
        print(f"\n⚠ 净值曲线生成失败: {e}")

    return report, signals


def main():
    parser = argparse.ArgumentParser(description="A股模拟盘 每日主程序")
    parser.add_argument("--pre-market", action="store_true", help="盘前信号模式")
    parser.add_argument("--settle", action="store_true", help="收盘结算模式")
    parser.add_argument("--date", type=str, default=None, help="指定日期 YYYY-MM-DD")
    parser.add_argument("--init-db", action="store_true", help="仅初始化数据库")
    args = parser.parse_args()

    # 指定日期
    trade_date = None
    if args.date:
        from datetime import datetime
        trade_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    # 初始化数据库
    print("🔧 检查数据库...")
    init_tables()

    if args.init_db:
        print("✅ 数据库初始化完成")
        return

    if args.pre_market:
        run_pre_market()
    elif args.settle:
        run_settle(trade_date)
    else:
        # 默认：完整流程
        run_settle(trade_date)


if __name__ == "__main__":
    main()
