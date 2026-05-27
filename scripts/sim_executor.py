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


def _load_max_total() -> float:
    """从 config.yaml 读取学习账户总额上限，默认 200000。"""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
        v = cfg.get('accounts', {}).get('learn', {}).get('max_total_value')
        if v:
            return float(v)
    except Exception:
        pass
    return 200000.0


_LEARN_MAX_TOTAL: float = _load_max_total()  # 动态读 config.yaml accounts.learn.max_total_value


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
DEFAULT_BUY_BUDGET = 10000  # 单次买入预算（单只约总资金 5-10%）

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
                 commission: float, tax: float, signal_reason: str, trade_context: dict = None):
    import json as _json
    from datetime import datetime as _dt
    now = _dt.now()
    trade_time_str = now.strftime('%H:%M:%S')  # 北京时间 HH:MM:SS
    ctx_json = _json.dumps(trade_context, ensure_ascii=False) if trade_context else None
    conn = get_conn()
    conn.execute(
        """INSERT INTO sim_trades 
           (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, commission, tax, signal_reason, broker, trade_time, trade_context)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_ACCOUNT_ID, date.today().isoformat(), code, name, direction, price, qty, price*qty,
         commission, tax, signal_reason, 'live_mirror' if _ACCOUNT_ID == 1 else 'real_mirror', trade_time_str, ctx_json)
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


def _check_trend_gate(rule: dict, action: str) -> tuple[bool, str]:
    """趋势过滤闸：根据 watchlist[code].trend_filter.gate 决定是否放行买入。
    
    Returns: (passed, reason)
      - True → 放行
      - False → 拦截，带上原因
    
    仅对 BUY 动作生效，SELL 不受影响（止损是必须的）。
    """
    if not action.startswith('BUY'):
        return True, ''
    
    # 人工冻结（如电信）最高优先级
    if rule.get('auto_buy_disabled'):
        return False, f"⛔ auto_buy_disabled=true: {rule.get('auto_buy_disabled_reason', '人工冻结')}"
    
    tf = rule.get('trend_filter', {}) or {}
    gate = tf.get('gate', 'auto')
    
    if gate == 'auto':
        return True, ''
    if gate == 'frozen':
        return False, f"⛔ trend_filter=frozen (status={tf.get('status')}, last/MA60={tf.get('last_vs_ma60_pct')}%) — 趋势已坏，等右侧确认"
    if gate == 'require_support':
        # 左侧买入：必须同时有"价格支撑 + 量能企稳"两重信号
        ok, reason = _check_left_side_support(rule.get('code', ''), tf)
        if ok:
            return True, f'⚡ require_support 检查通过: {reason}'
        return False, f"🔍 require_support — {reason}"
    if gate == 'manual_only':
        # WEAK 是 MA20<MA60，DIRTY 是 ATR 过高
        status = tf.get('status', '')
        if status == 'DIRTY':
            return False, f"✋ trend_filter=manual_only (status=DIRTY, ATR={tf.get('atr_pct')}%) — 波动太大，趋势信号不可信"
        return False, f"✋ trend_filter=manual_only (MA20<MA60 {tf.get('ma20_vs_ma60_pct')}%) — 均线还空头，仅提醒不自动"
    if gate == 'wait_volume':
        # 实时检查近 3 日均量 vs 过去 20 日 baseline
        vol_ok = _realtime_vol_ok(rule.get('code', ''))
        if vol_ok:
            return True, '⚡ trend_filter=wait_volume 但实时检查量能已放大，放行'
        return False, f"📊 trend_filter=wait_volume (vol×{tf.get('vol_ratio', 0):.2f}) — 缩量金叉无效，等量能放大"
    if gate == 'wait_macd':
        # 实时检查 MACD 是否金叉了（可能上次检测后变了）
        macd_ok = _realtime_macd_ok(rule.get('code', ''))
        if macd_ok:
            return True, '⚡ trend_filter=wait_macd 但实时检查 MACD 已金叉，放行'
        return False, f"⏳ trend_filter=wait_macd — MACD 未金叉，等右侧确认"
    return True, ''


_VOL_CACHE: dict[str, tuple[float, bool]] = {}  # code -> (cached_at_ts, vol_ok)
_SUPPORT_CACHE: dict[str, tuple[float, bool, str]] = {}  # code -> (cached_at_ts, ok, reason)


def _check_left_side_support(code: str, tf: dict) -> tuple[bool, str]:
    """左侧买入支撑检查。
    
    必须同时满足两个条件才能买：
    1. 价格支撑：在 MA60 附近不破 或 在近 60 日低点附近企稳
    2. 量能企稳：今日量 ≥ 近 5 日均量 × 0.8（不能是无量阴跌）
    ⚡ 加分（其中一项满足即可）：
      - 今日收红（close > open）且量比 ≥ 1.0 —— 启动信号
      - 近 3 日有一个探低反弹日（low 创近期新低但 close 是阳线）
    """
    if not code:
        return False, '股票代码为空'
    import time
    now_ts = time.time()
    cached = _SUPPORT_CACHE.get(code)
    if cached and (now_ts - cached[0]) < _MACD_CACHE_TTL_SEC:
        return cached[1], cached[2]
    
    try:
        import baostock as bs
        import pandas as pd
        from datetime import datetime, timedelta
        prefix = 'sh' if code.startswith('6') else 'sz'
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')
        bs.login()
        try:
            rs = bs.query_history_k_data_plus(
                f'{prefix}.{code}', 'date,open,high,low,close,volume',
                start_date=start, end_date=end, frequency='d', adjustflag='2'
            )
            rows = []
            while rs.error_code == '0' and rs.next():
                rows.append(rs.get_row_data())
        finally:
            bs.logout()
        if len(rows) < 60:
            _SUPPORT_CACHE[code] = (now_ts, False, '数据不足 60 日')
            return False, '数据不足 60 日'
        
        df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume'])
        for c in ['open','high','low','close','volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna()
        
        last_close = float(df['close'].iloc[-1])
        last_open = float(df['open'].iloc[-1])
        last_low = float(df['low'].iloc[-1])
        ma60 = float(df['close'].tail(60).mean())
        low60 = float(df['low'].tail(60).min())
        avg_vol5 = float(df['volume'].tail(5).mean())
        today_vol = float(df['volume'].iloc[-1])
        vol_ratio = (today_vol / avg_vol5) if avg_vol5 > 0 else 0
        
        # 条件 1：价格支撑
        # 带一点宽民：MA60 × 0.99 以上 OR 近 60 日低点×1.05 以内
        near_ma60 = last_close >= ma60 * 0.99
        near_low60 = last_close <= low60 * 1.05
        if not (near_ma60 or near_low60):
            reason = f'未在支撑区 (last¥{last_close:.2f}, MA60¥{ma60:.2f}, 60日低¥{low60:.2f})'
            _SUPPORT_CACHE[code] = (now_ts, False, reason)
            return False, reason
        
        # 条件 2：量能不缩 (动量判断企稳)
        if vol_ratio < 0.8:
            reason = f'量能过缩 (今日量={vol_ratio:.2f}×5日均)，无量阴跌不能买'
            _SUPPORT_CACHE[code] = (now_ts, False, reason)
            return False, reason
        
        # 启动信号：今日收红 + 量比 ≥ 1
        if last_close > last_open and vol_ratio >= 1.0:
            reason = f'✅ 价位在支撑区 + 今日量比{vol_ratio:.2f} 收红 — 启动信号'
            _SUPPORT_CACHE[code] = (now_ts, True, reason)
            return True, reason
        
        # 探低反弹：近 3 日有 low 创近 60 日新低 但 close 阳线且量量比 ≥ 1
        for i in range(-3, 0):
            row = df.iloc[i]
            if (float(row['low']) <= low60 * 1.01 and
                float(row['close']) > float(row['open']) and
                float(row['volume']) >= avg_vol5):
                reason = f'✅ 近 3 日有探低反弹日 ({row["date"]} 收红量比{float(row["volume"])/avg_vol5:.2f})'
                _SUPPORT_CACHE[code] = (now_ts, True, reason)
                return True, reason
        
        reason = f'🔍 价位在支撑区但未见启动 (今日{("阳" if last_close>last_open else "阴")}, 量比{vol_ratio:.2f}) — 等企稳'
        _SUPPORT_CACHE[code] = (now_ts, False, reason)
        return False, reason
    except Exception as e:
        logger.warning(f"_check_left_side_support({code}) failed: {e}")
        return False, f'检查异常: {e}'


def _realtime_vol_ok(code: str) -> bool:
    """实时检查最近 3 日均量 vs 过去 20 日均量，比例 >= 1.0 算量能配合。带 10 分钟缓存。"""
    if not code:
        return False
    import time
    now_ts = time.time()
    cached = _VOL_CACHE.get(code)
    if cached and (now_ts - cached[0]) < _MACD_CACHE_TTL_SEC:
        return cached[1]
    try:
        import baostock as bs
        from datetime import datetime, timedelta
        prefix = 'sh' if code.startswith('6') else 'sz'
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
        bs.login()
        try:
            rs = bs.query_history_k_data_plus(
                f'{prefix}.{code}', 'date,volume',
                start_date=start, end_date=end, frequency='d', adjustflag='2'
            )
            rows = []
            while rs.error_code == '0' and rs.next():
                rows.append(rs.get_row_data())
        finally:
            bs.logout()
        if len(rows) < 23:
            _VOL_CACHE[code] = (now_ts, False)
            return False
        vols = [float(r[1]) for r in rows if r[1]]
        recent3 = sum(vols[-3:]) / 3
        baseline20 = sum(vols[-23:-3]) / 20
        result = bool(baseline20 > 0 and recent3 / baseline20 >= 1.0)
        _VOL_CACHE[code] = (now_ts, result)
        return result
    except Exception as e:
        logger.warning(f"_realtime_vol_ok({code}) failed: {e}")
        return False


_MACD_CACHE: dict[str, tuple[float, bool]] = {}  # code -> (cached_at_ts, macd_ok)
_MACD_CACHE_TTL_SEC: float = 600.0  # 缓存 10 分钟够了，同一轮 portfolio_alert 肯定复用


def _realtime_macd_ok(code: str) -> bool:
    """实时拉最近 80 日收盘，检查是否 MACD 金叉且 DIF>0。带 10 分钟 TTL 缓存。"""
    if not code:
        return False
    import time
    now_ts = time.time()
    cached = _MACD_CACHE.get(code)
    if cached and (now_ts - cached[0]) < _MACD_CACHE_TTL_SEC:
        return cached[1]
    try:
        import baostock as bs
        import pandas as pd
        from datetime import datetime, timedelta
        prefix = 'sh' if code.startswith('6') else 'sz'
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
        bs.login()
        try:
            rs = bs.query_history_k_data_plus(
                f'{prefix}.{code}', 'date,close',
                start_date=start, end_date=end, frequency='d', adjustflag='2'
            )
            rows = []
            while rs.error_code == '0' and rs.next():
                rows.append(rs.get_row_data())
        finally:
            bs.logout()
        if len(rows) < 30:
            _MACD_CACHE[code] = (now_ts, False)
            return False
        closes = pd.Series([float(r[1]) for r in rows if r[1]])
        ema_fast = closes.ewm(span=12, adjust=False).mean()
        ema_slow = closes.ewm(span=26, adjust=False).mean()
        dif = (ema_fast - ema_slow).iloc[-1]
        dea = (ema_fast - ema_slow).ewm(span=9, adjust=False).mean().iloc[-1]
        result = bool(dif > dea and dif > 0)
        _MACD_CACHE[code] = (now_ts, result)
        return result
    except Exception as e:
        logger.warning(f"_realtime_macd_ok({code}) failed: {e}")
        return False


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

    # 🚺 趋势过滤闸（frozen / wait_macd / manual_only 会拦截 BUY）
    gate_ok, gate_reason = _check_trend_gate(rule, action)
    if not gate_ok:
        logger.info(f"🚽 [{code}] {action} 被 trend_filter 拦截: {gate_reason}")
        return {
            'action': 'NO_ACTION', 'success': True,
            'message': f'信号触发但被趋势过滤闸拦截: {gate_reason}',
            'trade': None
        }
    if gate_reason:
        logger.info(f"✅ [{code}] {action} {gate_reason}")

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
        _sell_ctx = {
            'strategy': '阈值触发',
            'rule_level': rule['level'],
            'trigger_price': rule.get('trigger', 0),
            'signal_msg': rule.get('message', ''),
            'sell_reason': f"触发{rule['level']}卖出规则",
            'price_at_trigger': cur_price,
            'position_qty_before': pos['quantity'],
            'avg_cost': pos['avg_cost'],
            'pnl_pct': round((cur_price - pos['avg_cost']) / pos['avg_cost'] * 100, 2),
        }
        insert_trade(code, name, 'SELL', cur_price, sell_qty, commission, tax,
                     f"自动: {rule['level']} | {rule['message'][:50]}",
                     trade_context=_sell_ctx)
        
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
        # 获取持仓上限配置
        try:
            import yaml
            from pathlib import Path
            cfg_path = Path(__file__).resolve().parents[1] / "config.yaml"
            cfg = yaml.safe_load(cfg_path.read_text(encoding='utf-8'))
            max_pos_pct = cfg.get('risk', {}).get('max_position_pct', 0.15)
        except Exception:
            max_pos_pct = 0.15

        import datetime
        now_time = datetime.datetime.now().time()
        morning_limit = datetime.time(10, 0)
        is_early_morning = now_time < morning_limit

        if action == 'BUY_LIGHT':
            # 试探买入：总资金的 2% 或现金的 10%，取小
            budget = min(100000 * 0.02, cash * 0.1)
        else:  # BUY_HEAVY
            # 加仓买入：总资金的 5% 或现金的 20%，取小
            budget = min(100000 * 0.05, cash * 0.2)

        # 方案B: 早盘大跌不急买，10:00 前强制限缩买入规模（砍半或更低）
        if is_early_morning:
            budget = budget * 0.5  # 早盘预算减半

        # 检查买入后是否超个股最大仓位限制
        cur_total = account.get('total_value', 100000.0)
        current_pos_value = 0
        if pos:
            current_pos_value = pos['quantity'] * cur_price
        
        if (current_pos_value + budget) > cur_total * max_pos_pct:
            budget = cur_total * max_pos_pct - current_pos_value
            
        if budget < cur_price * LOT_SIZE * 1.001:  # 至少够买 1 手 + 手续费
            return {'action': action, 'success': False,
                    'message': f'买入受限，需要 {cur_price*LOT_SIZE:.0f}，预算/额度剩余仅 {budget:.0f}（个股上限 {max_pos_pct*100}%）', 'trade': None}
        
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
        _buy_ctx = {
            'strategy': '阈值触发',
            'rule_level': rule['level'],
            'trigger_price': rule.get('trigger', 0),
            'signal_msg': rule.get('message', ''),
            'buy_type': action,  # BUY_LIGHT / BUY_HEAVY
            'budget': round(budget, 0),
            'price_at_trigger': cur_price,
            'ma_info': rule.get('message', ''),  # MA10/MA20 信息在 message 里
        }
        insert_trade(code, name, 'BUY', cur_price, buy_qty, commission, 0,
                     f"自动: {rule['level']} | {rule['message'][:50]}",
                     trade_context=_buy_ctx)
        
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
