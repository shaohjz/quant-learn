"""
波段自动交易脚本 v2
====================
使用 sim_executor 的现有功能来执行波段交易
账户: swing_trade (account_id=3)
"""

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))

import sqlite3
import datetime
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'data' / 'sim_live_mirror.db'
LOG_PATH = ROOT / 'logs' / f'swing_auto_{datetime.date.today().isoformat()}.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('swing_auto_v2')

SWING_ACCOUNT_ID = 3
MAX_POSITIONS = 5
SINGLE_POSITION_BUDGET = 10000  # 单笔上限1万
STOP_LOSS_PCT = 0.05
TAKE_PROFIT_PCT = 0.10
TRAILING_ACTIVATE_PCT = 0.05
COMMISSION_RATE = 0.00025
STAMP_TAX_RATE = 0.0005
LOT_SIZE = 100
EXECUTABLE_TYPES = {'A', 'B'}
MIN_SCORE = 5

from sim_executor import (
    set_active_account,
    calc_commission, calc_stamp_tax,
    quantize_price, quantize_amount,
    update_position_trailing, update_all_positions_market_value,
    _ensure_trailing_columns,
)


def get_swing_signals(scan_date: str = None) -> list:
    if scan_date is None:
        scan_date = datetime.date.today().isoformat()
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute(
        "SELECT * FROM swing_scan_results WHERE scan_date=? AND signal_type IN ('A','B') ORDER BY score DESC",
        (scan_date,)
    )
    cols = [d[0] for d in cur.description]
    signals = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return signals


def get_positions(account_id: int = SWING_ACCOUNT_ID) -> list:
    conn = sqlite3.connect(str(DB_PATH))
    _ensure_trailing_columns(conn)
    cur = conn.execute(
        "SELECT * FROM sim_positions WHERE account_id=? AND quantity>0",
        (account_id,)
    )
    cols = [d[0] for d in cur.description]
    positions = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return positions


def get_account(account_id: int = SWING_ACCOUNT_ID) -> dict:
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute("SELECT * FROM sim_account WHERE id=?", (account_id,))
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    conn.close()
    return dict(zip(cols, row)) if row else {}


def get_tencent_quote(code: str) -> dict | None:
    import urllib.request
    url = f'https://qt.gtimg.cn/q={code}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode('gbk')
        vals = data.split('"')[1].split('~')
        return {
            'name': vals[1], 'price': float(vals[3]),
            'high': float(vals[33]), 'low': float(vals[34]),
            'change_pct': float(vals[32]),
            'volume': int(vals[6]) if vals[6] else 0,
        }
    except Exception as e:
        logger.warning(f"获取行情失败 {code}: {e}")
        return None


def buy_stock(account_id, code, name, price, reason):
    """使用 sim_executor 风格的买入逻辑"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("BEGIN")
        acct = conn.execute("SELECT cash FROM sim_account WHERE id=?", (account_id,)).fetchone()
        if not acct:
            conn.execute("ROLLBACK")
            return {'success': False, 'message': '账户不存在'}
        cash = float(acct[0])

        budget = min(cash * 0.95, SINGLE_POSITION_BUDGET)
        qty = max(LOT_SIZE, int(budget / price / LOT_SIZE) * LOT_SIZE)
        # 确保不超过现金
        while qty * price > cash * 0.95 and qty > LOT_SIZE:
            qty -= LOT_SIZE
        if qty <= 0:
            conn.execute("ROLLBACK")
            return {'success': False, 'message': f'预算不足: cash={cash:.0f}, price={price:.2f}'}

        amount = price * qty
        commission = calc_commission(amount)
        total_cost = amount + commission
        if total_cost > cash:
            conn.execute("ROLLBACK")
            return {'success': False, 'message': f'现金不足: need={total_cost:.0f}, have={cash:.0f}'}

        # 扣现金
        conn.execute("UPDATE sim_account SET cash=cash-?, total_value=total_value-? WHERE id=?", (total_cost, total_cost, account_id))
        # 订单
        conn.execute("INSERT INTO sim_orders (account_id, stock_code, stock_name, direction, price, quantity, traded, status, signal_reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
                     (account_id, code, name, 'BUY', price, qty, qty, 'filled', reason))
        # 成交
        conn.execute("INSERT INTO sim_fills (account_id, stock_code, stock_name, direction, trade_price, trade_volume, trade_amount, commission, created_at) VALUES (?,?,?,?,?,?,?,?,datetime('now','localtime'))",
                     (account_id, code, name, 'BUY', price, qty, total_cost, commission))
        # 交易记录
        conn.execute("INSERT INTO sim_trades (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, signal_reason, created_at, trade_time) VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))",
                     (account_id, datetime.date.today().isoformat(), code, name, 'BUY', price, qty, total_cost, commission, reason))
        # 持仓
        existing = conn.execute("SELECT id, quantity, avg_cost FROM sim_positions WHERE account_id=? AND stock_code=?", (account_id, code)).fetchone()
        if existing:
            old_qty, old_cost = existing[1], existing[2]
            new_qty = old_qty + qty
            new_cost = (old_cost * old_qty + price * qty) / new_qty
            conn.execute("UPDATE sim_positions SET quantity=?, avg_cost=?, current_price=?, market_value=?, updated_at=datetime('now','localtime') WHERE id=?", (new_qty, new_cost, price, price * new_qty, existing[0]))
        else:
            conn.execute("INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, updated_at) VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))",
                         (account_id, code, name, qty, price, price, price * qty))

        conn.commit()
        logger.info(f"✅ BUY {code} {name} {qty}股@{price:.2f} 金额{total_cost:.2f}")
        return {'success': True, 'message': f'买入{qty}股@{price:.2f}', 'qty': qty, 'amount': total_cost}
    except Exception as e:
        conn.execute("ROLLBACK")
        logger.error(f"买入失败 {code}: {e}")
        return {'success': False, 'message': str(e)}
    finally:
        conn.close()


def sell_stock(account_id, position, price, reason):
    """卖出持仓"""
    code = position['stock_code']
    name = position['stock_name']
    qty = position['quantity']
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("BEGIN")
        amount = price * qty
        commission = calc_commission(amount)
        stamp_tax = calc_stamp_tax(amount)
        net_amount = amount - commission - stamp_tax

        conn.execute("UPDATE sim_account SET cash=cash+?, total_value=total_value+? WHERE id=?", (net_amount, net_amount, account_id))
        conn.execute("INSERT INTO sim_orders (account_id, stock_code, stock_name, direction, price, quantity, traded, status, signal_reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
                     (account_id, code, name, 'SELL', price, qty, qty, 'filled', reason))
        conn.execute("INSERT INTO sim_fills (account_id, stock_code, stock_name, direction, trade_price, trade_volume, trade_amount, commission, created_at) VALUES (?,?,?,?,?,?,?,?,datetime('now','localtime'))",
                     (account_id, code, name, 'SELL', price, qty, net_amount, commission))
        conn.execute("INSERT INTO sim_trades (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, signal_reason, created_at, trade_time) VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))",
                     (account_id, datetime.date.today().isoformat(), code, name, 'SELL', price, qty, net_amount, commission, reason))
        # TASK-20260718-2003-001: 清仓后 DELETE 而非 UPDATE SET quantity=0，避免幽灵持仓残留。
        conn.execute("DELETE FROM sim_positions WHERE id=?", (position['id'],))
        # REQ-058: 清仓后级联失效 threshold_state
        try:
            from sim.sell_signal_audit import expire_thresholds_on_flat
            expire_thresholds_on_flat(
                conn.cursor(), code, note=f"swing_v2清仓|{reason}",
            )
        except Exception:
            pass
        conn.commit()
        logger.info(f"✅ SELL {code} {name} {qty}股@{price:.2f} 净额{net_amount:.2f}")
        return {'success': True, 'message': f'卖出{qty}股@{price:.2f}', 'qty': qty, 'amount': net_amount}
    except Exception as e:
        conn.execute("ROLLBACK")
        logger.error(f"卖出失败 {code}: {e}")
        return {'success': False, 'message': str(e)}
    finally:
        conn.close()


def check_stops(positions, quotes):
    """检查止损止盈"""
    actions = []
    for pos in positions:
        code = pos['stock_code']
        q = None
        for prefix in ['sh', 'sz']:
            if prefix + code in quotes:
                q = quotes[prefix + code]
                break
        if not q:
            continue
        price = q['price']
        cost = pos['avg_cost']
        pnl_pct = (price - cost) / cost
        trailing = pos.get('trailing_stop_price')

        # 更新跟踪止损
        highest = pos.get('highest_price')
        if highest and price > highest:
            new_trailing = price * (1 - TRAILING_ACTIVATE_PCT)
            conn = sqlite3.connect(str(DB_PATH))
            conn.execute("UPDATE sim_positions SET highest_price=?, trailing_stop_price=?, current_price=?, market_value=?, pnl=?, pnl_pct=?, updated_at=datetime('now','localtime') WHERE id=?",
                         (price, new_trailing, price, price * pos['quantity'], (price - cost) * pos['quantity'], pnl_pct * 100, pos['id']))
            conn.commit()
            conn.close()

        if trailing and price <= trailing:
            actions.append({'type': 'stop_loss', 'position': pos, 'price': price, 'reason': f'跟踪止损: 价{price:.2f}≤止损{trailing:.2f}'})
        elif pnl_pct <= -STOP_LOSS_PCT:
            actions.append({'type': 'stop_loss', 'position': pos, 'price': price, 'reason': f'固定止损: 浮亏{pnl_pct*100:.1f}%'})
        elif pnl_pct >= TAKE_PROFIT_PCT:
            actions.append({'type': 'take_profit', 'position': pos, 'price': price, 'reason': f'止盈: 浮盈{pnl_pct*100:.1f}%'})
    return actions


def run():
    today = datetime.date.today().isoformat()
    logger.info(f"🚀 波段自动交易 v2 - {today}")
    set_active_account(SWING_ACCOUNT_ID)

    account = get_account()
    logger.info(f"💰 现金{account.get('cash',0):.2f} 总资产{account.get('total_value',0):.2f}")

    positions = get_positions()
    logger.info(f"📊 持仓: {len(positions)}只")
    for p in positions:
        logger.info(f"   {p['stock_code']} {p['stock_name']} {p['quantity']}股 成本{p['avg_cost']:.2f}")

    # 止损检查
    codes = [f"{pre}{p['stock_code']}" for p in positions for pre in ['sh', 'sz']]
    quotes = {}
    for c in set(codes):
        q = get_tencent_quote(c)
        if q:
            quotes[c] = q

    stop_actions = check_stops(positions, quotes)
    for a in stop_actions:
        r = sell_stock(SWING_ACCOUNT_ID, a['position'], a['price'], a['reason'])
        logger.info(f"  {'✅' if r['success'] else '❌'} {a['type']}: {a['reason']}")

    # 买入信号
    signals = get_swing_signals(today)
    logger.info(f"📡 信号: {len(signals)}条")
    positions = get_positions()
    if len(positions) >= MAX_POSITIONS:
        logger.info(f"⏭️ 持仓已满({MAX_POSITIONS}只)")
    else:
        buys = []
        for sig in signals:
            clean = sig['stock_code'].replace('sh', '').replace('sz', '')
            if any(p['stock_code'] == clean for p in positions):
                continue
            if sig.get('score', 0) < MIN_SCORE:
                continue
            q = get_tencent_quote(sig['stock_code'])
            if not q:
                continue
            buys.append({'code': clean, 'name': sig['stock_name'], 'price': q['price'],
                         'score': sig['score'], 'type': sig['signal_type'],
                         'signals': sig['signals'], 'rr': sig.get('risk_reward', 0)})
        buys.sort(key=lambda x: x['score'], reverse=True)
        slots = MAX_POSITIONS - len(positions)
        for sig in buys[:slots]:
            reason = f"波段|{sig['type']}类 score={sig['score']} {sig['signals']}"
            r = buy_stock(SWING_ACCOUNT_ID, sig['code'], sig['name'], sig['price'], reason)
            logger.info(f"  {'✅' if r['success'] else '❌'} BUY {sig['code']} {sig['name']} @{sig['price']:.2f} -> {r['message']}")

    # 最终状态
    account = get_account()
    positions = get_positions()
    logger.info(f"\n📊 最终状态:")
    logger.info(f"  现金: {account.get('cash',0):.2f}")
    logger.info(f"  总资产: {account.get('total_value',0):.2f}")
    for p in positions:
        pnl = (p['current_price'] - p['avg_cost']) * p['quantity']
        logger.info(f"    {p['stock_code']} {p['stock_name']} {p['quantity']}股 成本{p['avg_cost']:.2f} 现价{p['current_price']:.2f} 浮盈{pnl:.2f}")
    logger.info("✅ 完成")


if __name__ == '__main__':
    run()
