"""
sim/review_lib.py — 周/月复盘共用工具
提供日期范围内的双账户聚合统计：
  - 实现盈亏（FIFO 配对）
  - 浮动盈亏（snapshot）
  - 交易笔数
  - 胜率
  - nav 起点/终点 + 区间收益
"""
from __future__ import annotations
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import List, Dict, Any

ACCOUNTS = [
    {'id': 1, 'name': '学习账户', 'icon': '🤖'},
    {'id': 2, 'name': '真实账户', 'icon': '💼'},
]


def get_conn(db_path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    return c


def fetch_account(conn, account_id: int):
    r = conn.execute('SELECT * FROM sim_account WHERE id=?', (account_id,)).fetchone()
    return dict(r) if r else None


def fetch_positions(conn, account_id: int):
    rows = conn.execute(
        'SELECT * FROM sim_positions WHERE account_id=? ORDER BY market_value DESC',
        (account_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_trades_in_range(conn, account_id: int, start: date, end: date) -> List[Dict]:
    """[start, end] 闭区间，过滤掉 legacy broker"""
    rows = conn.execute(
        '''SELECT * FROM sim_trades 
           WHERE account_id=? AND trade_date BETWEEN ? AND ?
             AND COALESCE(broker, '') NOT LIKE '%legacy%'
           ORDER BY trade_date, id''',
        (account_id, start.isoformat(), end.isoformat())
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_nav_in_range(conn, account_id: int, start: date, end: date):
    rows = conn.execute(
        '''SELECT * FROM sim_daily_nav 
           WHERE account_id=? AND trade_date BETWEEN ? AND ? 
           ORDER BY trade_date''',
        (account_id, start.isoformat(), end.isoformat())
    ).fetchall()
    return [dict(r) for r in rows]


def compute_realized_pnl_in_range(conn, account_id: int, start: date, end: date) -> List[Dict]:
    """FIFO 配对，返回 [start, end] 区间内每笔 SELL 的实现盈亏"""
    # 拉所有截至 end 的非 legacy 交易（包括 start 之前的 BUY 用于配对）
    rows = conn.execute(
        '''SELECT * FROM sim_trades 
           WHERE account_id=? AND trade_date<=? 
             AND COALESCE(broker, '') NOT LIKE '%legacy%'
           ORDER BY trade_date, id''',
        (account_id, end.isoformat())
    ).fetchall()

    queues = defaultdict(list)  # code -> [[qty, price, fee_per_share]]
    realized_in_range = []

    for r in rows:
        code = r['stock_code']
        d = r['direction']
        qty = r['quantity']
        price = r['price']
        fee = (r['commission'] or 0) + (r['tax'] or 0)
        fee_per = fee / qty if qty else 0
        is_in_range = (start.isoformat() <= r['trade_date'] <= end.isoformat())

        if d == 'BUY':
            queues[code].append([qty, price, fee_per])
        elif d == 'SELL':
            remaining = qty
            cost_total = 0.0
            buy_fee_total = 0.0
            while remaining > 0 and queues[code]:
                head = queues[code][0]
                take = min(head[0], remaining)
                cost_total += take * head[1]
                buy_fee_total += take * head[2]
                head[0] -= take
                remaining -= take
                if head[0] == 0:
                    queues[code].pop(0)

            if is_in_range and qty - remaining > 0:
                consumed = qty - remaining
                sell_amount = consumed * price
                sell_fee = fee * (consumed / qty)
                pnl = sell_amount - cost_total - buy_fee_total - sell_fee
                avg_cost = cost_total / consumed if consumed > 0 else 0
                pnl_pct = (price / avg_cost - 1) * 100 if avg_cost > 0 else 0
                realized_in_range.append({
                    'date': r['trade_date'],
                    'code': code,
                    'name': r['stock_name'],
                    'qty': consumed,
                    'sell_price': price,
                    'avg_cost': avg_cost,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                })

    return realized_in_range


def aggregate_period(conn, account_id: int, start: date, end: date) -> Dict[str, Any]:
    """聚合一段时间的统计"""
    trades = fetch_trades_in_range(conn, account_id, start, end)
    realized = compute_realized_pnl_in_range(conn, account_id, start, end)
    nav = fetch_nav_in_range(conn, account_id, start, end)
    account = fetch_account(conn, account_id)
    positions = fetch_positions(conn, account_id)

    buys = [t for t in trades if t['direction'] == 'BUY']
    sells = [t for t in trades if t['direction'] == 'SELL']

    total_realized = sum(r['pnl'] for r in realized)
    wins = [r for r in realized if r['pnl'] > 0]
    losses = [r for r in realized if r['pnl'] <= 0]
    win_rate = len(wins) / len(realized) * 100 if realized else 0
    profit_factor = (sum(r['pnl'] for r in wins) / abs(sum(r['pnl'] for r in losses))
                     if losses and sum(r['pnl'] for r in losses) != 0 else 0)

    floating = sum(p['pnl'] for p in positions)

    # 区间收益
    if nav:
        start_value = nav[0]['total_value']
        end_value = nav[-1]['total_value']
        period_return = (end_value / start_value - 1) * 100 if start_value > 0 else 0
        # 取区间内每条 daily_return 算累乘验证
    else:
        start_value = end_value = (account['initial_cash'] if account else 0)
        period_return = 0

    return {
        'account_id': account_id,
        'account_name': account['account_name'] if account else 'unknown',
        'cash': account['cash'] if account else 0,
        'total_value': account['total_value'] if account else 0,
        'positions': positions,
        'trades': trades,
        'realized': realized,
        'nav': nav,
        'buys_n': len(buys),
        'sells_n': len(sells),
        'realized_total': total_realized,
        'wins_n': len(wins),
        'losses_n': len(losses),
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'floating': floating,
        'start_value': start_value,
        'end_value': end_value,
        'period_return': period_return,
    }


def fmt_currency(v: float) -> str:
    """格式化货币"""
    return f"{v:+,.2f}" if v != 0 else "0.00"
