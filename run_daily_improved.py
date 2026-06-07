#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_daily_improved.py — 改进版A股每日主程序
优化买入信号执行率，解决现金不足问题
"""

import sys
import os
import argparse
from datetime import date as Date
import heapq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 确保所需目录存在
from scripts.ensure_dirs import ensure_dirs
ensure_dirs()

from sim.db import init_tables
from sim.signal_generator import generate_signals, dedupe_signals
from sim.stock_pool import StockPool
from sim.realtime_price import get_latest_prices
from sim.reporter import generate_daily_report, generate_nav_chart
from sim.config import risk_params, broker_mode
from sim.trade_calendar import is_trading_day
from sim import notifier
from broker import get_broker


# 风控参数
_RISK = risk_params()
MAX_POSITION_PCT = _RISK["max_position_pct"]
DAILY_MAX_TRADES = _RISK["max_daily_trades"]
STOP_LOSS_PCT = _RISK["stop_loss_pct"]
TAKE_PROFIT_PCT = _RISK["take_profit_pct"]
MAX_DAILY_BUILD_AMOUNT_PCT = _RISK["max_daily_build_amount_pct"]
LIQUIDITY_RELEASE_LOSS_THRESHOLD = _RISK["liquidity_release_loss_threshold"]


def _build_existing_position_map(broker):
    """构建持仓映射"""
    out = {}
    for p in broker.get_positions():
        out[p.stock_code] = {
            "quantity": p.quantity,
            "avg_cost": p.avg_cost,
            "max_price_since_buy": p.current_price if p.current_price > 0 else p.avg_cost,
        }
    return out


def _release_liquidity(broker, needed_cash: float, max_sell_ratio: float = 0.5) -> float:
    """
    释放流动性：优先卖出浮亏超阈值的仓位以获取现金
    
    策略（REQ-045）：
    1. 优先卖出浮亏超过 liquidity_release_loss_threshold（默认8%）的仓位
    2. 若 still not enough，再卖其他浮亏仓位
    3. 按亏损幅度排序（亏得最多的优先卖）
    
    Args:
        broker: 经纪商接口
        needed_cash: 需要的现金金额
        max_sell_ratio: 单个持仓最大卖出比例（防止过度卖出）
    
    Returns:
        实际释放的现金金额
    """
    positions = broker.get_positions()
    if not positions:
        return 0.0
    
    loss_threshold = LIQUIDITY_RELEASE_LOSS_THRESHOLD  # 默认 8%
    
    # 1. 分类持仓：深亏（>threshold）、浅亏、浮盈
    deep_loss = []   # 浮亏超过阈值的
    shallow_loss = []  # 浮亏但未超阈值的
    
    for pos in positions:
        if pos.quantity <= 0:
            continue
        pnl_pct = (pos.current_price - pos.avg_cost) / pos.avg_cost if pos.avg_cost > 0 else 0
        if pnl_pct < -loss_threshold:
            heapq.heappush(deep_loss, (pnl_pct, pos))  # 深亏优先
        elif pnl_pct < 0:
            shallow_loss.append((pnl_pct, pos))
        # 浮盈的不主动卖
    
    if not deep_loss and not shallow_loss:
        print(f"  → 无浮亏仓位可卖（阈值为 {-loss_threshold:.0%}），无法释放流动性")
        return 0.0
    
    released_cash = 0.0
    sold_positions = []
    
    print(f"  → 尝试释放流动性，需要 ¥{needed_cash:,.2f}")
    print(f"  → 深亏(>{ -loss_threshold:.0%})仓位数: {len(deep_loss)}，浅亏仓位数: {len(shallow_loss)}")
    
    # 2. 先卖深亏仓位（按亏损幅度从大到小）
    to_sell = []
    while deep_loss:
        pnl_pct, pos = heapq.heappop(deep_loss)  # 最小堆，最负的在最前
        to_sell.append((pnl_pct, pos))
    # 再卖浅亏仓位
    # shallow_loss 按亏损幅度排序（亏得多的在前）
    shallow_loss.sort(key=lambda x: x[0])  # 升序，最负的在前
    to_sell.extend(shallow_loss)
    
    for pnl_pct, pos in to_sell:
        if released_cash >= needed_cash:
            break
        
        # 计算卖出数量（最多卖一半，避免过度卖出）
        max_sell_qty = int(pos.quantity * max_sell_ratio / 100) * 100
        if max_sell_qty < 100:
            max_sell_qty = pos.quantity  # 如果太少就全卖
        
        # 执行卖出
        result = broker.sell(
            stock_code=pos.stock_code,
            price=pos.current_price,
            quantity=max_sell_qty,
            stock_name=pos.stock_name,
            signal_reason=f"释放流动性(浮亏{(pnl_pct*100):.1f}%)",
            trade_date=Date.today()
        )
        
        if result.success:
            released_cash += result.amount - result.commission - result.tax
            sold_positions.append({
                "code": pos.stock_code,
                "name": pos.stock_name,
                "quantity": max_sell_qty,
                "price": pos.current_price,
                "pnl_pct": pnl_pct
            })
            print(f"  → 卖出 {pos.stock_name}({pos.stock_code}) {max_sell_qty}股 @ {pos.current_price:.2f} 释放 ¥{result.amount:,.2f} [浮亏{(pnl_pct*100):.1f}%]")
    
    if sold_positions:
        print(f"  ✓ 共释放流动性 ¥{released_cash:,.2f}")
    else:
        print(f"  → 释放流动性失败")
    
    return released_cash


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

    # 2. 生成信号（去重：同一股票同日只保留第一个买入信号）
    pos_map = _build_existing_position_map(broker)
    # 2. 生成信号
    raw_signals = []
    for code, name in pool.get_all().items():
        sig = generate_signals(code, name, existing_position=pos_map.get(code))
        raw_signals.append(sig)

    # REQ-051: 同一股票同日多信号去重（取最高优先级信号，忽略其余）
    signals = dedupe_signals(raw_signals, trade_date=str(trade_date))

    buy_signals_count = sum(1 for s in signals if s["signal"] == "BUY")
    sell_signals_count = sum(1 for s in signals if s["signal"] == "SELL")

    for sig in signals:
        emoji = "🟢" if sig["signal"] == "BUY" else "🔴" if sig["signal"] == "SELL" else "⚪"
        print(f"\n{emoji} {sig['name']}({sig['code']}): {sig['signal']}")
        print(f"  原因: {', '.join(sig['reasons'])}")

    print(f"\n📊 信号统计: {buy_signals_count}个买入, {sell_signals_count}个卖出")

    # 3. 执行交易
    trades_today = 0
    positions_by_code = {p.stock_code: p for p in broker.get_positions()}
    
    # REQ-045: 单日最大建仓金额上限检查
    import sqlite3, os
    _DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sim_live_mirror.db")
    if not os.path.exists(_DB_PATH):
        _DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sim.db")
    _today_str = trade_date.isoformat()
    _account_id = 1  # learn 模拟盘
    
    # 查询今日已买入金额（含佣金税费）
    _conn = sqlite3.connect(_DB_PATH)
    try:
        _row = _conn.execute(
            "SELECT COALESCE(SUM(amount + commission + tax), 0) FROM sim_trades "
            "WHERE account_id=? AND direction='BUY' AND trade_date=?",
            (_account_id, _today_str)
        ).fetchone()
        today_bought_amount = _row[0] if _row else 0.0
    finally:
        _conn.close()
    
    # 计算今日还可建仓金额上限
    acct_for_limit = broker.get_account()
    total_assets = acct_for_limit.cash + acct_for_limit.total_value - acct_for_limit.cash  # 近似值
    # 更精确的总资产 = cash + sum(market_value of all positions)
    positions_for_assets = broker.get_positions()
    total_market_value = sum(p.market_value for p in positions_for_assets)
    total_assets = acct_for_limit.cash + total_market_value
    max_daily_build_amount = total_assets * MAX_DAILY_BUILD_AMOUNT_PCT
    remaining_build_amount = max(0, max_daily_build_amount - today_bought_amount)
    
    print(f"\n📊 [REQ-045 仓位管理] 单日建仓上限: ¥{max_daily_build_amount:,.2f} "
          f"(总资产¥{total_assets:,.2f}×{MAX_DAILY_BUILD_AMOUNT_PCT:.0%}), "
          f"今日已建: ¥{today_bought_amount:,.2f}, 剩余额度: ¥{remaining_build_amount:,.2f}")

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
            
            # 改进1：先检查现金是否足够
            min_investment = 100 * price  # 最小投资金额（1手）
            
            if acct.cash < min_investment:
                print(f"\n⚠️ 现金不足买入1手 {name}({code})，尝试释放流动性...")
                needed_cash = min_investment - acct.cash
                released = _release_liquidity(broker, needed_cash)
                
                if released <= 0:
                    print(f"  → 无法释放流动性，跳过 {name}({code})")
                    continue
                
                # 重新获取账户信息
                acct = broker.get_account()
            
            # 改进2：更智能的买入金额计算
            # 使用以下公式：min(可用现金×仓位上限, 可用现金-预留现金)
            reserve_cash = 1000  # 预留1000元作为安全边际
            available_cash = max(0, acct.cash - reserve_cash)
            max_amount = min(available_cash * MAX_POSITION_PCT, available_cash)
            
            if max_amount < price * 100:  # 不够买1手
                print(f"  → 买入金额不足1手({max_amount:.2f} < {price*100:.2f})，跳过 {name}({code})")
                continue
            
            quantity = (int(max_amount / price) // 100) * 100
            if quantity <= 0:
                print(f"  → 计算买入数量为0，跳过 {name}({code})")
                continue
            
            # 再次检查现金是否足够
            total_cost = price * quantity + max(price * quantity * 0.0003, 5)
            if total_cost > acct.cash:
                print(f"  → 现金不足(需{total_cost:.2f} > 可用{acct.cash:.2f})，跳过 {name}({code})")
                continue
            
            result = broker.buy(
                stock_code=code, price=price, quantity=quantity,
                stock_name=name,
                signal_reason=sig.get("signal_reason", "+".join(sig["reasons"])),
                trade_date=trade_date,
                signal_detail=sig.get("signal_detail"),
            )
            print(f"  → {'✅' if result.success else '❌'} 买入: {result.msg}")
            notifier.notify_trade("BUY", name, code, quantity, price,
                                   "+".join(sig["reasons"]), result.success)
            if result.success:
                trades_today += 1
            else:
                # 如果买入失败，可能是现金计算错误，尝试释放流动性
                if "资金不足" in result.msg:
                    print(f"  → 买入失败(资金不足)，尝试释放流动性...")
                    needed_cash = total_cost - acct.cash
                    _release_liquidity(broker, needed_cash)

        elif sig["signal"] == "SELL":
            pos = positions_by_code.get(code)
            if pos and pos.quantity > 0:
                result = broker.sell(
                    stock_code=code, price=price, quantity=pos.quantity,
                    stock_name=name,
                    signal_reason=sig.get("signal_reason", "+".join(sig["reasons"])),
                    trade_date=trade_date,
                    signal_detail=sig.get("signal_detail"),
                )
                print(f"  → {'✅' if result.success else '❌'} 卖出: {result.msg}")
                notifier.notify_trade("SELL", name, code, pos.quantity, price,
                                       "+".join(sig["reasons"]), result.success)
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

    # 6. 生成报告（REQ-026：风控建议需要读 sim_live_mirror.db）
    import os
    _db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sim_live_mirror.db")
    if not os.path.exists(_db_path):
        _db_path = None  # 回退到默认 sim.db
    report = generate_daily_report(trade_date, signals, db_path=_db_path)
    print("\n" + report)

    # 7. 生成净值曲线
    chart_path = None
    try:
        chart_path = generate_nav_chart()
        if chart_path:
            print(f"\n📈 净值曲线已保存: {chart_path}")
    except Exception as e:
        print(f"\n⚠ 净值曲线生成失败: {e}")

    # 8. 推送企微
    notifier.notify_signals(signals, trade_date)
    notifier.notify_daily_report(report, chart_path)

    return report, signals


def main():
    parser = argparse.ArgumentParser(description="A股每日主程序（模拟/实盘）")
    parser.add_argument("--mode", choices=["sim", "live"], default=None,
                        help="交易模式：sim=模拟盘 / live=实盘QMT；默认读 config.yaml broker.mode")
    parser.add_argument("--pre-market", action="store_true", help="盘前信号模式")
    parser.add_argument("--settle", action="store_true", help="收盘结算模式")
    parser.add_argument("--date", type=str, default=None, help="指定日期 YYYY-MM-DD")
    parser.add_argument("--init-db", action="store_true", help="仅初始化数据库")
    parser.add_argument("--force", action="store_true", help="非交易日也强制跑")
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

    # 交易日检查
    today = trade_date or Date.today()
    if not args.force and not is_trading_day(today):
        print(f"⏸ {today} 非交易日，跳过（加 --force 可强制运行）")
        return

    # 创建 broker
    mode = args.mode or broker_mode()
    broker = get_broker(mode=mode)
    print(f"✅ broker 已连接：{broker.name}")

    try:
        if args.pre_market:
            signals = run_pre_market(broker)
            notifier.notify_signals(signals)
        elif args.settle:
            run_settle(broker, trade_date)
        else:
            run_settle(broker, trade_date)
    finally:
        broker.disconnect()


if __name__ == "__main__":
    main()