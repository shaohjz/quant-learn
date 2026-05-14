#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_daily.py — A股每日主程序（支持模拟盘 / 实盘切换）

用法:
  python run_daily.py --pre-market           盘前信号（只生成信号，不交易）
  python run_daily.py --settle               收盘结算（执行交易 + 结算 + 报告）
  python run_daily.py                        默认：完整流程（信号→交易→结算→报告）
  python run_daily.py --mode live --settle   实盘模式（需 QMT 已配置）

环境变量（实盘模式必需）:
  QMT_USERDATA_MINI   QMT 的 userdata_mini 路径
  QMT_ACCOUNT_ID      资金账号
  QMT_SESSION_ID      （可选）xtquant 会话 ID
"""

import sys
import os
import argparse
from datetime import date as Date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sim.db import init_tables
from sim.signal_generator import generate_signals
from sim.stock_pool import StockPool
from sim.realtime_price import get_latest_prices
from sim.reporter import generate_daily_report, generate_nav_chart
from broker import get_broker


# 风控参数
MAX_POSITION_PCT = 0.60     # 单次开仓不超过总资金的 60%
DAILY_MAX_TRADES = 5        # 每日最多 5 笔
STOP_LOSS_PCT = -0.08       # 止损线 -8%
TAKE_PROFIT_PCT = 0.15      # 止盈线 +15%


def _build_existing_position_map(broker):
    """把 broker.get_positions() 转成 generate_signals 需要的 existing_position 字典"""
    out = {}
    for p in broker.get_positions():
        out[p.stock_code] = {
            "quantity": p.quantity,
            "avg_cost": p.avg_cost,
            "max_price_since_buy": p.current_price if p.current_price > 0 else p.avg_cost,
        }
    return out


def run_pre_market(broker):
    """盘前模式：只生成信号"""
    print("=" * 50)
    print(f"🌅 盘前信号分析  [broker={broker.name}]")
    print("=" * 50)

    pool = StockPool()
    pos_map = _build_existing_position_map(broker)

    signals = []
    for code, name in pool.get_all().items():
        sig = generate_signals(code, name, existing_position=pos_map.get(code))
        signals.append(sig)
        emoji = "🟢" if sig["signal"] == "BUY" else "🔴" if sig["signal"] == "SELL" else "⚪"
        print(f"\n{emoji} {name}({code}): {sig['signal']}")
        print(f"  原因: {', '.join(sig['reasons'])}")

    return signals


def run_settle(broker, trade_date: Date = None):
    """收盘结算：行情→信号→交易→更新→结算→报告"""
    trade_date = trade_date or Date.today()
    print("=" * 50)
    print(f"🌆 收盘结算 ({trade_date})  [broker={broker.name}]")
    print("=" * 50)

    pool = StockPool()

    # 1. 获取最新价格
    codes = pool.get_codes()
    prices_data = get_latest_prices(codes)
    price_map = {c: d["price"] for c, d in prices_data.items() if d["price"] > 0}
    name_map = pool.get_all()
    for c, d in prices_data.items():
        if d.get("name") and not name_map.get(c):
            name_map[c] = d["name"]

    print(f"\n📡 行情: {', '.join(f'{name_map.get(c,c)} ¥{p:.2f}' for c, p in price_map.items())}")

    # 2. 生成信号
    pos_map = _build_existing_position_map(broker)
    signals = []
    for code, name in pool.get_all().items():
        sig = generate_signals(code, name, existing_position=pos_map.get(code))
        signals.append(sig)
        emoji = "🟢" if sig["signal"] == "BUY" else "🔴" if sig["signal"] == "SELL" else "⚪"
        print(f"\n{emoji} {name}({code}): {sig['signal']}")
        print(f"  原因: {', '.join(sig['reasons'])}")

    # 3. 执行交易（通过 broker 抽象，sim/live 同一套代码）
    trades_today = 0
    positions_by_code = {p.stock_code: p for p in broker.get_positions()}

    for sig in signals:
        if trades_today >= DAILY_MAX_TRADES:
            print(f"\n⛔ 已达每日最大交易笔数 {DAILY_MAX_TRADES}，跳过剩余信号")
            break

        code = sig["code"]
        name = sig["name"]
        price = price_map.get(code, sig.get("price", 0))
        if price <= 0:
            continue

        if sig["signal"] == "BUY":
            acct = broker.get_account()
            max_amount = acct.cash * MAX_POSITION_PCT
            quantity = (int(max_amount / price) // 100) * 100
            if quantity > 0:
                result = broker.buy(
                    stock_code=code, price=price, quantity=quantity,
                    stock_name=name, signal_reason="+".join(sig["reasons"]),
                    trade_date=trade_date,
                )
                print(f"  → {'✅' if result.success else '❌'} 买入: {result.msg}")
                if result.success:
                    trades_today += 1
            else:
                print(f"  → 买入信号但资金不足({code})")

        elif sig["signal"] == "SELL":
            pos = positions_by_code.get(code)
            if pos and pos.quantity > 0:
                result = broker.sell(
                    stock_code=code, price=price, quantity=pos.quantity,
                    stock_name=name, signal_reason="+".join(sig["reasons"]),
                    trade_date=trade_date,
                )
                print(f"  → {'✅' if result.success else '❌'} 卖出: {result.msg}")
                if result.success:
                    trades_today += 1
            else:
                print(f"  → 卖出信号但无持仓({code})")

    # 4. 更新持仓现价
    if price_map:
        broker.update_prices(price_map)
        print("\n  ✓ 持仓价格已更新")

    # 5. 每日结算
    settle = broker.daily_settle(trade_date)
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
    parser = argparse.ArgumentParser(description="A股每日主程序（模拟/实盘）")
    parser.add_argument("--mode", choices=["sim", "live"], default="sim",
                        help="交易模式：sim=模拟盘（默认） / live=实盘QMT")
    parser.add_argument("--pre-market", action="store_true", help="盘前信号模式")
    parser.add_argument("--settle", action="store_true", help="收盘结算模式")
    parser.add_argument("--date", type=str, default=None, help="指定日期 YYYY-MM-DD")
    parser.add_argument("--init-db", action="store_true", help="仅初始化数据库")
    args = parser.parse_args()

    trade_date = None
    if args.date:
        from datetime import datetime
        trade_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    print("🔧 检查数据库...")
    init_tables()

    if args.init_db:
        print("✅ 数据库初始化完成")
        return

    # 创建 broker
    broker = get_broker(mode=args.mode)
    print(f"✅ broker 已连接：{broker.name}")

    try:
        if args.pre_market:
            run_pre_market(broker)
        elif args.settle:
            run_settle(broker, trade_date)
        else:
            run_settle(broker, trade_date)
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()
