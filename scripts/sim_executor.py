#!/usr/bin/env python
"""
scripts/sim_executor.py — 阈值触发自动虚拟下单

模式 A 全自动：
  - portfolio_alert 检测到阈值触发后调用本模块
  - 根据 rule.level 自动决策买入/卖出/止损/止盈
  - 写入 sim_trades，更新 sim_positions/sim_account
  - 同时触发"换股"决策器（卖现有持仓买更优标的）

A股交易费率（粗略模拟）:
  买入: 佣金 0.025%（万2.5），最低 5 元
  卖出: 佣金 0.025% + 印花税 0.05%
"""
import os
import sys
from datetime import datetime, date
from pathlib import Path

# 强制使用 live_mirror DB
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

from sim.db import get_conn

import logging
logger = logging.getLogger(__name__)

# ============================================================
# 双账户架构（2026-05-22）
#   id=1 live_mirror    → 学习账户（自动下单）
#   id=2 real_portfolio → 真实账户（仅告警，不下单）
# 调用方设 set_active_account(2) 可切换；但 execute_trade 会拒绝真实账户下单。
# ============================================================
_ACCOUNT_ID: int = int(os.environ.get('SIM_ACCOUNT_ID', '1'))
_LEARN_MAX_TOTAL: float = 100000.0  # 学习账户总额上限（现金+持仓市值）


def set_active_account(account_id: int) -> None:
    global _ACCOUNT_ID
    _ACCOUNT_ID = int(account_id)


def active_account_id() -> int:
    return _ACCOUNT_ID

# A股最小交易单位 100 股

# 涨跌停阈值（主板 10%，创业板/科创板 20%）
def _get_limit_pct(code: str) -> float:
    """返回该股票的涨跌停限制（0.10 或 0.20）"""
    if code.startswith(('30', '68')):  # 创业板 / 科创板
        return 0.20
    if code.startswith(('8', '4')):  # 北交所 30%
        return 0.30
    return 0.10  # 主板 / 中小板


def _get_yesterday_close(code: str) -> float | None:
    """从新浪拿 yesterday_close。失败返回 None。"""
    try:
        from sim.realtime_price import fetch_sina_realtime
        r = fetch_sina_realtime([code])
        if code in r and r[code].get('yesterday_close', 0) > 0:
            return r[code]['yesterday_close']
    except Exception:
        pass
    return None


def check_price_sanity(code: str, cur_price: float, action: str) -> tuple[bool, str]:
    """检查价格合理性。返回 (ok, reason)。抦截接近涨跌停的买卖。"""
    yc = _get_yesterday_close(code)
    if not yc or yc <= 0:
        return True, "无昨收价参考，跳过检查"

    limit_pct = _get_limit_pct(code)

    if action.startswith('BUY'):
        # 接近涨停不买（0.5% 安全边际）
        cap = yc * (1 + limit_pct * 0.95)
        if cur_price >= cap:
            return False, f"价格 {cur_price:.2f} 接近涨停阈 {cap:.2f}（昨收 {yc:.2f} +{limit_pct*100:.0f}%），拒买入"
        # 当前价 等于 昨收 是可疑伪实时价（baostock fallback 返昨日收盘）
        if abs(cur_price - yc) < 0.005:
            return False, f"价格 {cur_price:.2f} == 昨收价 {yc:.2f}，可疑 fallback 返回昨收价冲实时，拒买入"

    elif action.startswith('SELL'):
        floor = yc * (1 - limit_pct * 0.95)
        if cur_price <= floor:
            return False, f"价格 {cur_price:.2f} 接近跌停阈 {floor:.2f}（昨收 {yc:.2f} -{limit_pct*100:.0f}%），拒卖出"

    return True, "价格合理"

LOT_SIZE = 100

# 默认每次买入的金额上限（避免一把梭）
DEFAULT_BUY_BUDGET = 2000  # 单次试探买不超过 2000 元

# 费率
COMMISSION_RATE = 0.00025  # 万2.5
COMMISSION_MIN = 5.0
TAX_RATE = 0.0005          # 印花税仅卖出


def calc_commission(amount: float) -> float:
    """佣金（最低5元）"""
    return max(amount * COMMISSION_RATE, COMMISSION_MIN)


def get_account():
    conn = get_conn()
    row = conn.execute("SELECT * FROM sim_account WHERE id=?", (_ACCOUNT_ID,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_position(code: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sim_positions WHERE stock_code=? AND account_id=?",
        (code, _ACCOUNT_ID)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_account_cash(delta: float):
    """delta 正数=资金增加，负数=资金减少"""
    conn = get_conn()
    conn.execute(
        "UPDATE sim_account SET cash = cash + ?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (delta, _ACCOUNT_ID)
    )
    conn.close()


def insert_trade(code: str, name: str, direction: str, price: float, qty: int,
                 commission: float, tax: float, signal_reason: str):
    conn = get_conn()
    conn.execute(
        """INSERT INTO sim_trades 
           (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, tax, signal_reason, broker)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_ACCOUNT_ID, date.today().isoformat(), code, name, direction, price, qty, price*qty,
         commission, tax, signal_reason, 'live_mirror' if _ACCOUNT_ID == 1 else 'real_mirror')
    )
    conn.close()


def upsert_position(code: str, name: str, qty: int, avg_cost: float, cur_price: float):
    """新建或更新持仓。qty=0 时删除"""
    conn = get_conn()
    if qty <= 0:
        conn.execute(
            "DELETE FROM sim_positions WHERE stock_code=? AND account_id=?",
            (code, _ACCOUNT_ID)
        )
    else:
        market_value = qty * cur_price
        pnl = (cur_price - avg_cost) * qty
        pnl_pct = (cur_price/avg_cost - 1) * 100 if avg_cost > 0 else 0
        # 用 UPSERT 模式
        existing = conn.execute(
            "SELECT id FROM sim_positions WHERE stock_code=? AND account_id=?",
            (code, _ACCOUNT_ID)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE sim_positions SET quantity=?, avg_cost=?, current_price=?, market_value=?, pnl=?, pnl_pct=?, updated_at=CURRENT_TIMESTAMP
                   WHERE stock_code=? AND account_id=?""",
                (qty, avg_cost, cur_price, market_value, pnl, pnl_pct, code, _ACCOUNT_ID)
            )
        else:
            conn.execute(
                """INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_ACCOUNT_ID, code, name, qty, avg_cost, cur_price, market_value, pnl, pnl_pct)
            )
    conn.close()


# ========================================================================
#  决策器：根据 rule.level 决定动作
# ========================================================================
def decide_action(rule: dict, cur_price: float):
    """
    根据 rule.level 返回动作：
      'BUY_LIGHT' 试探买（约 1 手）
      'BUY_HEAVY' 加仓买（约 2 手或预算用尽）
      'SELL_HALF' 卖一半
      'SELL_ALL' 全部卖
      'NO_ACTION' 仅提醒不操作
    """
    level = rule.get("level", "")
    
    # 持仓股止损止盈
    if level in ("stop_loss", "soft_stop"):
        return 'SELL_HALF'
    if level in ("hard_stop", "deep_drop"):
        return 'SELL_ALL'
    if level in ("take_profit_half", "take_half"):
        return 'SELL_HALF'
    if level in ("take_profit", "take_full"):
        return 'SELL_ALL'
    
    # 观察股买入
    if level == "buy_zone":
        return 'BUY_LIGHT'
    if level == "buy_strong":
        return 'BUY_HEAVY'
    
    # 不操作
    if level == "trend_break":
        return 'NO_ACTION'  # 观察股趋势破位 → 不买
    
    return 'NO_ACTION'


def execute_trade(rule: dict, cur_price: float) -> dict:
    """
    根据规则执行虚拟交易。
    
    Returns:
        dict: {
            'action': str,  # 实际做的动作
            'success': bool,
            'message': str,  # 描述
            'trade': dict | None  # 交易细节
        }
    """
    code = rule["code"]
    name = rule["name"]
    action = decide_action(rule, cur_price)
    
    if action == 'NO_ACTION':
        return {'action': action, 'success': True, 'message': '仅提醒，不操作', 'trade': None}

    # ⛔ 真实账户拒绝任何下单（1=学习，2=真实）
    if _ACCOUNT_ID != 1:
        return {
            'action': action, 'success': False,
            'message': f'账户 id={_ACCOUNT_ID} 仅告警模式，不下单',
            'trade': None
        }

    # 价格合理性检查（涨跌停阈 + 伪实时价检测）
    sane, sane_reason = check_price_sanity(code, cur_price, action)
    if not sane:
        logger.warning(f"🚫 [{code}] 抦截下单: {sane_reason}")
        return {'action': action, 'success': False, 'message': f'价格安全检查未过: {sane_reason}', 'trade': None}
    
    account = get_account()
    if not account:
        return {'action': action, 'success': False, 'message': '账户不存在', 'trade': None}
    cash = account['cash']

    # 🔒 学习账户总额上限检查（现金+持仓市值 不得超 100k）
    # 注：cur_total > _LEARN_MAX_TOTAL 才拒绝（>= 会误伤初始账户刚好 100000 的状态）
    if action.startswith('BUY'):
        cur_total = account.get('total_value', 0) or 0
        # 加 buffer：初始 100000，第一次买后市值约等于现金（手续费小损耗），允许小幅波动
        if cur_total > _LEARN_MAX_TOTAL + 100:  # 100 元缓冲
            return {
                'action': action, 'success': False,
                'message': f'学习账户总额 {cur_total:.0f} 已超上限 {_LEARN_MAX_TOTAL:.0f}+100，拒绝买入',
                'trade': None
            }
    
    pos = get_position(code)
    
    # ----- 卖出 -----
    if action.startswith('SELL'):
        if not pos or pos['quantity'] <= 0:
            return {'action': action, 'success': False, 'message': f'{code} 无持仓可卖', 'trade': None}
        
        sell_qty = pos['quantity'] if action == 'SELL_ALL' else (pos['quantity'] // 2 // LOT_SIZE) * LOT_SIZE
        if sell_qty < LOT_SIZE:
            sell_qty = pos['quantity']  # 不到 1 手就全卖
        
        amount = sell_qty * cur_price
        commission = calc_commission(amount)
        tax = amount * TAX_RATE
        net_proceeds = amount - commission - tax
        
        # 写交易
        insert_trade(code, name, 'SELL', cur_price, sell_qty, commission, tax,
                     f"自动: {rule['level']} | {rule['message'][:30]}")
        
        # 更新现金 + 持仓
        update_account_cash(net_proceeds)
        new_qty = pos['quantity'] - sell_qty
        upsert_position(code, name, new_qty, pos['avg_cost'], cur_price)
        
        return {
            'action': action, 'success': True,
            'message': f'卖出 {name} {sell_qty}股 @{cur_price:.2f} = {amount:.2f}（净到手 {net_proceeds:.2f}）',
            'trade': {'direction': 'SELL', 'qty': sell_qty, 'price': cur_price, 'amount': amount, 'fee': commission+tax}
        }
    
    # ----- 买入 -----
    if action.startswith('BUY'):
        # 预算
        if action == 'BUY_LIGHT':
            budget = min(DEFAULT_BUY_BUDGET, cash * 0.5)  # 用一半现金或 2000 较小者
        else:  # BUY_HEAVY
            budget = min(DEFAULT_BUY_BUDGET * 2, cash * 0.8)
        
        if budget < cur_price * LOT_SIZE * 1.001:  # 至少够买 1 手 + 手续费
            return {'action': action, 'success': False,
                    'message': f'现金不足 {cash:.2f}，无法买 {code} 1 手 ({cur_price*LOT_SIZE:.2f})', 'trade': None}
        
        # 买多少手
        max_lots = int(budget / (cur_price * LOT_SIZE * 1.001))
        buy_qty = max_lots * LOT_SIZE
        amount = buy_qty * cur_price
        commission = calc_commission(amount)
        total_cost = amount + commission
        
        if total_cost > cash:
            return {'action': action, 'success': False,
                    'message': f'现金不够（需 {total_cost:.2f}，有 {cash:.2f}）', 'trade': None}
        
        # 写交易
        insert_trade(code, name, 'BUY', cur_price, buy_qty, commission, 0,
                     f"自动: {rule['level']} | {rule['message'][:30]}")
        
        # 更新现金
        update_account_cash(-total_cost)
        
        # 计算新成本价
        if pos:
            old_amount = pos['quantity'] * pos['avg_cost']
            new_qty = pos['quantity'] + buy_qty
            new_avg = (old_amount + amount + commission) / new_qty
        else:
            new_qty = buy_qty
            new_avg = (amount + commission) / new_qty
        
        upsert_position(code, name, new_qty, new_avg, cur_price)
        
        return {
            'action': action, 'success': True,
            'message': f'买入 {name} {buy_qty}股 @{cur_price:.2f} = {amount:.2f}（含费 {total_cost:.2f}）',
            'trade': {'direction': 'BUY', 'qty': buy_qty, 'price': cur_price, 'amount': amount, 'fee': commission}
        }
    
    return {'action': action, 'success': False, 'message': f'未知动作: {action}', 'trade': None}


def update_all_positions_market_value(prices: dict):
    """收盘/盘中更新所有持仓的市值（不改成本）"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT stock_code, quantity, avg_cost FROM sim_positions WHERE account_id=?",
        (_ACCOUNT_ID,)
    ).fetchall()
    for row in rows:
        code = row['stock_code']
        cur_price = prices.get(code, 0)
        if cur_price > 0:
            mv = row['quantity'] * cur_price
            pnl = (cur_price - row['avg_cost']) * row['quantity']
            pnl_pct = (cur_price/row['avg_cost'] - 1) * 100 if row['avg_cost'] > 0 else 0
            conn.execute(
                "UPDATE sim_positions SET current_price=?, market_value=?, pnl=?, pnl_pct=?, updated_at=CURRENT_TIMESTAMP WHERE stock_code=? AND account_id=?",
                (cur_price, mv, pnl, pnl_pct, code, _ACCOUNT_ID)
            )
    # 更新账户总市值
    total_mv = conn.execute(
        "SELECT COALESCE(SUM(market_value),0) AS s FROM sim_positions WHERE account_id=?",
        (_ACCOUNT_ID,)
    ).fetchone()['s']
    cash_row = conn.execute("SELECT cash FROM sim_account WHERE id=?", (_ACCOUNT_ID,)).fetchone()
    cash = cash_row['cash'] if cash_row else 0.0
    conn.execute(
        "UPDATE sim_account SET total_value=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (total_mv + cash, _ACCOUNT_ID)
    )
    conn.close()


if __name__ == "__main__":
    # 自检
    acc = get_account()
    print(f"账户: id={_ACCOUNT_ID} {acc['account_name']} / 现金 {acc['cash']:.2f} / 总值 {acc['total_value']:.2f}")
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sim_positions WHERE account_id=?", (_ACCOUNT_ID,)).fetchall()
    for r in rows:
        print(f"  {r['stock_code']} {r['stock_name']:>6} {r['quantity']:>4}股 @{r['avg_cost']:.3f} 现价{r['current_price']:.2f} 浮亏{r['pnl']:+.2f} ({r['pnl_pct']:+.2f}%)")
    conn.close()
