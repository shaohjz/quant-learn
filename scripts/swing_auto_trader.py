"""
波段自动交易脚本
================
流程: 波段扫描 → 信号筛选 → 执行买卖 → 推送结果

账户: swing_trade (account_id=3)
初始资金: 50,000元
策略: 仅执行A类(最优)和B类(良好)信号，单笔不超过总资金20%
"""

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))

import sqlite3
import json
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
logger = logging.getLogger('swing_auto')

# ── 波段账户配置 ──────────────────────────────────────────────────────────
SWING_ACCOUNT_ID = 3
# 资金真源：config.yaml accounts.swing.initial_cash（缺失时兜底 5 万）
try:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from sim.config import account_initial_cash as _account_initial_cash
    SWING_INITIAL_CASH = _account_initial_cash(SWING_ACCOUNT_ID)
except Exception:
    SWING_INITIAL_CASH = 50000.0
MAX_POSITIONS = 5          # 最多同时持有5只
SINGLE_POSITION_PCT = 0.20  # 单只上限20%
STOP_LOSS_PCT = 0.05       # 固定止损5%
TAKE_PROFIT_PCT = 0.10     # 止盈10%
TRAILING_ACTIVATE_PCT = 0.05  # 浮盈5%后启动跟踪止损
COMMISSION_RATE = 0.00025  # 万2.5
STAMP_TAX_RATE = 0.0005    # 万5（仅卖出）
LOT_SIZE = 100

# ── 信号质量门槛 ──────────────────────────────────────────────────────────
# A类: 缩量回踩均线（最优）
# B类: 布林下轨+RSI超卖（良好）
# C类: 仅RSI超卖（一般，不自动执行）
# D类: 仅布林下轨（一般，不自动执行）
EXECUTABLE_TYPES = {'A', 'B'}
MIN_SCORE = 5  # 最低评分

# ── 导入模拟执行器功能 ─────────────────────────────────────────────────────
from sim_executor import (
    set_active_account, active_account_id,
    calc_commission, calc_stamp_tax,
    quantize_price, quantize_amount,
    update_position_trailing, update_all_positions_market_value,
    _ensure_trailing_columns,
)

# ── 数据库操作 ─────────────────────────────────────────────────────────────

def get_swing_signals(scan_date: str = None) -> list:
    """获取当日波段扫描信号，按质量排序"""
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


def get_current_positions(account_id: int = SWING_ACCOUNT_ID) -> list:
    """获取当前持仓"""
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


def get_account_info(account_id: int = SWING_ACCOUNT_ID) -> dict:
    """获取账户信息"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute(
        "SELECT * FROM sim_account WHERE id=?", (account_id,)
    )
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    conn.close()
    return dict(zip(cols, row)) if row else {}


def has_position(positions: list, code: str) -> bool:
    """检查是否已持仓"""
    clean_code = code.replace('sh', '').replace('sz', '')
    for p in positions:
        if p['stock_code'] == clean_code:
            return True
    return False


def get_tencent_quote(code: str) -> dict | None:
    """获取实时行情"""
    import urllib.request
    url = f'https://qt.gtimg.cn/q={code}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode('gbk')
        vals = data.split('"')[1].split('~')
        return {
            'name': vals[1],
            'price': float(vals[3]),
            'high': float(vals[33]),
            'low': float(vals[34]),
            'change_pct': float(vals[32]),
            'volume': int(vals[6]) if vals[6] else 0,
        }
    except Exception as e:
        logger.warning(f"获取行情失败 {code}: {e}")
        return None


# ── 交易执行 ───────────────────────────────────────────────────────────────

def execute_buy(account_id: int, code: str, name: str, price: float, reason: str) -> dict:
    """执行买入"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("BEGIN")
        
        # 检查账户余额
        acct = conn.execute(
            "SELECT cash FROM sim_account WHERE id=?", (account_id,)
        ).fetchone()
        if not acct:
            conn.execute("ROLLBACK")
            return {'success': False, 'message': '账户不存在'}
        
        cash = float(acct[0])
        
        # 计算买入数量（单笔不超过总资金20%，但至少1手）
        max_amount = SWING_INITIAL_CASH * SINGLE_POSITION_PCT
        budget = min(cash * 0.95, max_amount)
        # 至少买1手
        min_qty = LOT_SIZE
        qty = max(min_qty, int(budget / price / LOT_SIZE) * LOT_SIZE)
        # 检查是否超过现金
        while qty * price > cash * 0.95 and qty > min_qty:
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
        conn.execute(
            "UPDATE sim_account SET cash=cash-?, total_value=total_value-? WHERE id=?",
            (total_cost, total_cost, account_id)
        )
        
        # 写入订单
        conn.execute(
            "INSERT INTO sim_orders (account_id, stock_code, stock_name, direction, price, quantity, traded, status, signal_reason, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
            (account_id, code, name, 'BUY', price, qty, qty, 'filled', reason)
        )
        
        # 写入成交
        conn.execute(
            "INSERT INTO sim_fills (account_id, stock_code, stock_name, direction, trade_price, trade_volume, trade_amount, commission, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,datetime('now','localtime'))",
            (account_id, code, name, 'BUY', price, qty, total_cost, commission)
        )
        
        # 写入交易记录
        conn.execute(
            "INSERT INTO sim_trades (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, signal_reason, created_at, trade_time) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))",
            (account_id, datetime.date.today().isoformat(), code, name, 'BUY', price, qty, total_cost, commission, reason)
        )
        
        # 更新/插入持仓
        existing = conn.execute(
            "SELECT id, quantity, avg_cost FROM sim_positions WHERE account_id=? AND stock_code=?",
            (account_id, code)
        ).fetchone()
        
        if existing:
            old_qty = existing[1]
            old_cost = existing[2]
            new_qty = old_qty + qty
            new_cost = (old_cost * old_qty + price * qty) / new_qty
            conn.execute(
                "UPDATE sim_positions SET quantity=?, avg_cost=?, current_price=?, market_value=?, updated_at=datetime('now','localtime') WHERE id=?",
                (new_qty, new_cost, price, price * new_qty, existing[0])
            )
        else:
            conn.execute(
                "INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, updated_at) "
                "VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))",
                (account_id, code, name, qty, price, price, price * qty)
            )
        
        conn.commit()
        logger.info(f"✅ BUY {code} {name} {qty}股@{price:.2f} 金额{total_cost:.2f}")
        return {'success': True, 'message': f'买入{qty}股@{price:.2f}', 'qty': qty, 'amount': total_cost}
    
    except Exception as e:
        conn.execute("ROLLBACK")
        logger.error(f"买入失败 {code}: {e}")
        return {'success': False, 'message': str(e)}
    finally:
        conn.close()


def execute_sell(account_id: int, position: dict, price: float, reason: str) -> dict:
    """执行卖出"""
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
        
        # 加现金
        conn.execute(
            "UPDATE sim_account SET cash=cash+?, total_value=total_value+? WHERE id=?",
            (net_amount, net_amount, account_id)
        )
        
        # 写入订单
        conn.execute(
            "INSERT INTO sim_orders (account_id, stock_code, stock_name, direction, price, quantity, amount, status, signal_reason, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
            (account_id, code, name, 'SELL', price, qty, net_amount, 'filled', reason)
        )
        
        # 写入成交
        conn.execute(
            "INSERT INTO sim_fills (account_id, stock_code, stock_name, direction, price, quantity, amount, commission, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,datetime('now','localtime'))",
            (account_id, code, name, 'SELL', price, qty, net_amount, commission)
        )
        
        # 写入交易记录
        conn.execute(
            "INSERT INTO sim_trades (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, signal_reason, created_at, trade_time) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))",
            (account_id, datetime.date.today().isoformat(), code, name, 'SELL', price, qty, net_amount, commission, reason)
        )
        
        # TASK-20260718-2003-001: 清仓后 DELETE 而非 UPDATE SET quantity=0，避免幽灵持仓残留。
        conn.execute("DELETE FROM sim_positions WHERE id=?", (position['id'],))
        # REQ-058: 清仓后级联失效 threshold_state
        try:
            from sim.sell_signal_audit import expire_thresholds_on_flat
            expire_thresholds_on_flat(
                conn.cursor(), code, note=f"swing清仓|{reason}",
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


# ── 主逻辑 ─────────────────────────────────────────────────────────────────

def check_stop_loss(positions: list, quotes: dict) -> list:
    """检查持仓是否需要止损/止盈"""
    actions = []
    for pos in positions:
        code = pos['stock_code']
        # 尝试带前缀查询
        for prefix in ['sh', 'sz']:
            key = f"{prefix}{code}"
            if key in quotes:
                q = quotes[key]
                break
        else:
            continue
        
        price = q['price']
        cost = pos['avg_cost']
        pnl_pct = (price - cost) / cost
        
        trailing = pos.get('trailing_stop_price')
        highest = pos.get('highest_price')
        
        # 更新跟踪止损
        if highest and price > highest:
            # 创新高，抬高止损
            new_trailing = price * (1 - TRAILING_ACTIVATE_PCT)
            conn = sqlite3.connect(str(DB_PATH))
            conn.execute(
                "UPDATE sim_positions SET highest_price=?, trailing_stop_price=?, current_price=?, market_value=?, pnl=?, pnl_pct=?, updated_at=datetime('now','localtime') WHERE id=?",
                (price, new_trailing, price, price * pos['quantity'], (price - cost) * pos['quantity'], pnl_pct * 100, pos['id'])
            )
            conn.commit()
            conn.close()
        
        # 止损检查
        if trailing and price <= trailing:
            actions.append({
                'type': 'stop_loss',
                'position': pos,
                'price': price,
                'reason': f'跟踪止损触发: 当前价{price:.2f} ≤ 止损价{trailing:.2f}'
            })
        elif pnl_pct <= -STOP_LOSS_PCT:
            actions.append({
                'type': 'stop_loss',
                'position': pos,
                'price': price,
                'reason': f'固定止损触发: 浮亏{pnl_pct*100:.1f}% ≤ -{STOP_LOSS_PCT*100:.0f}%'
            })
        elif pnl_pct >= TAKE_PROFIT_PCT:
            actions.append({
                'type': 'take_profit',
                'position': pos,
                'price': price,
                'reason': f'止盈触发: 浮盈{pnl_pct*100:.1f}% ≥ {TAKE_PROFIT_PCT*100:.0f}%'
            })
    
    return actions


def run_swing_trade():
    """主流程：波段扫描信号 → 执行买卖"""
    today = datetime.date.today().isoformat()
    logger.info(f"🚀 波段自动交易启动 - {today}")
    
    # 1. 切换到波段账户
    set_active_account(SWING_ACCOUNT_ID)
    logger.info(f"📋 使用账户: swing_trade (id={SWING_ACCOUNT_ID})")
    
    # 2. 获取账户信息
    account = get_account_info()
    logger.info(f"💰 账户余额: 现金{account.get('cash',0):.2f}, 总资产{account.get('total_value',0):.2f}")
    
    # 3. 获取当前持仓
    positions = get_current_positions()
    logger.info(f"📊 当前持仓: {len(positions)}只")
    for p in positions:
        logger.info(f"   {p['stock_code']} {p['stock_name']} {p['quantity']}股 成本{p['avg_cost']:.2f}")
    
    # 4. 检查持仓止损/止盈
    logger.info("🔍 检查持仓止损/止盈...")
    # 获取所有持仓的实时行情
    codes_to_check = []
    for p in positions:
        for prefix in ['sh', 'sz']:
            codes_to_check.append(f"{prefix}{p['stock_code']}")
    
    quotes = {}
    for c in codes_to_check:
        q = get_tencent_quote(c)
        if q:
            quotes[c] = q
    
    stop_actions = check_stop_loss(positions, quotes)
    for action in stop_actions:
        pos = action['position']
        result = execute_sell(SWING_ACCOUNT_ID, pos, action['price'], action['reason'])
        logger.info(f"  {'✅' if result['success'] else '❌'} {action['type']}: {action['reason']} -> {result['message']}")
    
    # 5. 获取当日波段信号
    signals = get_swing_signals(today)
    logger.info(f"📡 当日波段信号: {len(signals)}条")
    
    # 6. 筛选可执行信号
    positions = get_current_positions()  # 重新获取（可能有卖出）
    if len(positions) >= MAX_POSITIONS:
        logger.info(f"⏭️ 持仓已达上限({MAX_POSITIONS}只)，跳过买入")
    else:
        buy_signals = []
        for sig in signals:
            clean_code = sig['stock_code'].replace('sh', '').replace('sz', '')
            if has_position(positions, clean_code):
                logger.info(f"⏭️ 已持仓 {sig['stock_code']} {sig['stock_name']}，跳过")
                continue
            if sig.get('score', 0) < MIN_SCORE:
                logger.info(f"⏭️ 评分不足 {sig['stock_code']} score={sig['score']} < {MIN_SCORE}")
                continue
            
            # 获取实时行情确认
            q = get_tencent_quote(sig['stock_code'])
            if not q:
                continue
            
            buy_signals.append({
                'code': clean_code,
                'name': sig['stock_name'],
                'price': q['price'],
                'score': sig['score'],
                'signal_type': sig['signal_type'],
                'signals': sig['signals'],
                'risk_reward': sig.get('risk_reward', 0),
                'support': sig.get('support', 0),
                'resist': sig.get('resist', 0),
            })
        
        # 按评分排序，取前 N 只
        buy_signals.sort(key=lambda x: x['score'], reverse=True)
        slots = MAX_POSITIONS - len(positions)
        buy_signals = buy_signals[:slots]
        
        logger.info(f"🛒 计划买入: {len(buy_signals)}只")
        for sig in buy_signals:
            reason = f"波段信号|{sig['signal_type']}类 score={sig['score']} {sig['signals']}"
            result = execute_buy(SWING_ACCOUNT_ID, sig['code'], sig['name'], sig['price'], reason)
            logger.info(f"  {'✅' if result['success'] else '❌'} BUY {sig['code']} {sig['name']} @{sig['price']:.2f} -> {result['message']}")
    
    # 7. 更新所有持仓市值
    all_quotes = {}
    positions = get_current_positions()
    for p in positions:
        for prefix in ['sh', 'sz']:
            if f"{prefix}{p['stock_code']}" in quotes:
                all_quotes[f"{prefix}{p['stock_code']}"] = quotes[f"{prefix}{p['stock_code']}"]
    
    if all_quotes:
        update_all_positions_market_value(all_quotes, SWING_ACCOUNT_ID)
    
    # 8. 输出最终状态
    account = get_account_info()
    positions = get_current_positions()
    logger.info(f"\n📊 波段账户最终状态:")
    logger.info(f"  现金: {account.get('cash',0):.2f}")
    logger.info(f"  总资产: {account.get('total_value',0):.2f}")
    logger.info(f"  持仓: {len(positions)}只")
    for p in positions:
        pnl = (p['current_price'] - p['avg_cost']) * p['quantity']
        logger.info(f"    {p['stock_code']} {p['stock_name']} {p['quantity']}股 成本{p['avg_cost']:.2f} 现价{p['current_price']:.2f} 浮盈{pnl:.2f}")
    
    logger.info("✅ 波段自动交易完成")


if __name__ == '__main__':
    run_swing_trade()
