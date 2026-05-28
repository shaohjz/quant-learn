"""
sim_executor_v2.py — 修复买入执行率低的问题
======================================================================
根因：
  1. _check_left_side_support 要求 vol_ratio >= 0.8 才放行，过严
  2. _get_today_vol_ratio 获取失败时返回 None，导致 vol_ratio 为 None 不走买入
修复：
  1. 放宽 vol_ratio 阈值：0.8 → 0.6
  2. vol_ratio 为 None 时放行（只记录 warning）
"""

import os
import sys
import json
import logging
import sqlite3
from datetime import datetime, time as _dt_time
from pathlib import Path

# ── 强制使用 live_mirror DB ─────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))
_DB_PATH = os.environ['QUANT_DB_PATH']

from sim.db import get_conn

import logging
logger = logging.getLogger(__name__)

# ============================================================
# 双账户架构（2026-05-22）
#   id=1 live_mirror    → 学习账户（自动下单）
#   id=2 real_portfolio → 真实账户（仅告警，不下单）
# ============================================================
_ACCOUNT_ID: int = int(os.environ.get('SIM_ACCOUNT_ID', '1'))


def _load_max_total() -> float:
    """从 config.yaml 读取学习账户总额上限，默认 200000。"""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
        return float((cfg.get('accounts') or {}).get('learn', {}).get('max_total_value', 200000.0))
    except Exception:
        return 200000.0


def set_active_account(account_id: int):
    """切换当前操作账户（仅影响后续的买入/卖出执行）。"""
    global _ACCOUNT_ID
    _ACCOUNT_ID = int(account_id)
    logger.info(f"已切换到账户 id={account_id}")


def active_account_id() -> int:
    return _ACCOUNT_ID


# ── 全局缓存 ─────────────────────────────────────────────────────────────
_VOL_CACHE = {}          # code → (timestamp, vol_ratio)
_SUPPORT_CACHE = {}     # code → (timestamp, ok, reason)
_MACD_CACHE = {}       # code → (timestamp, ok)
_STOP_VOL_THRESH = 1.5   # 放量下跌阈值（放量 ≥1.5 倍确认止损）

# A股最小交易单位 100 股
LOT_SIZE = 100

# 默认每次买入的金额上限（避免一把梭）
DEFAULT_BUY_BUDGET = 10000   # 单次买入预算（单只约总资金 5-10%）

# 费率
COMMISSION_RATE = 0.00025   # 万2.5
STAMP_TAX_RATE = 0.0005   # 万5（仅卖出）


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
    """检查价格合理性。返回 (ok, reason)。⚠ 接近涨跌停的买卖。"""
    yc = _get_yesterday_close(code)
    if not yc or yc <= 0:
        return True, "无昨收价参考，跳过检查"

    limit_pct = 0.10   # 主板/中小板 10%
    if code.startswith(('30', '68')):   # 创业板/科创板 20%
        limit_pct = 0.20
    if code.startswith(('8', '4')):     # 北交所 30%
        limit_pct = 0.30

    if action.startswith('BUY'):
        cap = yc * (1 + limit_pct * 0.95)
        if cur_price >= cap:
            return False, f"价格 {cur_price:.2f} 接近涨停阈 {cap:.2f}（昨收 {yc:.2f} +{limit_pct*100:.0f}%），拒买入"
        # 当前价 等于 昨收价 是可疑伪实时价（baostock fallback 返回昨收）
        if abs(cur_price - yc) < 0.005:
            return False, f"价格 {cur_price:.2f} == 昨收价 {yc:.2f}，可疑 fallback 返回昨收价冲实时，拒买入"

    elif action.startswith('SELL'):
        floor = yc * (1 - limit_pct * 0.95)
        if cur_price <= floor:
            return False, f"价格 {cur_price:.2f} 接近跌停阈 {floor:.2f}（昨收 {yc:.2f} -{limit_pct*100:.0f}%），拒卖出"

    return True, "价格合理"


def _is_late_session() -> bool:
    """是否近收盘（14:50 后）。近收盘才执行止损动作，避盘中插针。"""
    now = datetime.now()
    return (now.hour > 14) or (now.hour == 14 and now.minute >= 50)


def _get_today_vol_ratio(code: str) -> float | None:
    """获取今日量 / 5 日均量 比值。带缓存。"""
    import time
    now_ts = time.time()
    cached = _VOL_CACHE.get(code)
    if cached and (now_ts - cached[0]) < 600:  # 10 分钟缓存
        return cached[1]

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
            while (rs.error_code == '0') and rs.next():
                rows.append(rs.get_row_data())
        finally:
            bs.logout()

        if len(rows) < 5:
            return None

        df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume'])
        for c in ['open','high','low','close','volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna()

        today_vol = float(df['volume'].iloc[-1])
        avg_vol5 = float(df['volume'].tail(5).mean())
        if avg_vol5 <= 0:
            return 0.0
        ratio = today_vol / avg_vol5
        _VOL_CACHE[code] = (now_ts, ratio)
        return ratio
    except Exception as e:
        logger.warning(f"_get_today_vol_ratio({code}) failed: {e}")
        return None


def _realtime_vol_ok(code: str) -> bool:
    """实时检查近 3 日均量 vs 过去 20 日 baseline。"""
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
            while (rs.error_code == '0') and rs.next():
                rows.append(rs.get_row_data())
        finally:
            bs.logout()

        if len(rows) < 20:
            return False

        df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume'])
        for c in ['open','high','low','close','volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna()

        avg_vol20 = float(df['volume'].tail(20).mean())
        if avg_vol20 <= 0:
            return False
        vol3 = float(df['volume'].tail(3).mean())
        return vol3 >= avg_vol20 * 0.8
    except Exception as e:
        logger.warning(f"_realtime_vol_ok({code}) failed: {e}")
        return False


def _realtime_macd_ok(code: str) -> bool:
    """实时检查 MACD 是否金叉了（可能上次检测后变了）。"""
    try:
        import baostock as bs
        import pandas as pd
        from datetime import datetime, timedelta
        import talib

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
            while (rs.error_code == '0') and rs.next():
                rows.append(rs.get_row_data())
        finally:
            bs.logout()

        if len(rows) < 26:
            return False

        df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume'])
        for c in ['open','high','low','close','volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna()

        close = df['close'].values
        dif, dea, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        if len(hist) < 2:
            return False
        # 最近两根 BAR 是否由负变正（金叉）
        return (hist[-2] < 0) and (hist[-1] >= 0)
    except Exception as e:
        logger.warning(f"_realtime_macd_ok({code}) failed: {e}")
        return False


def _check_left_side_support(code: str, tf: dict) -> tuple[bool, str]:
    """左侧买入支撑检查。
    
    必须同时满足两个条件才能买：
    1. 价格支撑：在 MA60 附近不破 或 在近 60 日低点企稳
    2. 量能企稳：今日量 ≥ 近 5 日均量 × 0.6（放宽从 0.8 → 0.6）
    ⚡ 加分（其中一项满足即可）：
      - 今日收红（close > open）且量比 ≥ 1.0 —— 启动信号
      - 近 3 日有一个探低反弹日（low 创近期新低但 close 阳线）
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
            while (rs.error_code == '0') and rs.next():
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
        vol_ratio = (today_vol / avg_vol5) if avg_vol5 > 0 else 0.0

        # 条件 1：价格支撑
        near_ma60 = last_close >= ma60 * 0.99
        near_low60 = last_close <= low60 * 1.05
        price_ok = near_ma60 or near_low60
        if not price_ok:
            reason = f"🔍 价位在支撑区但未见企稳 (MA60×0.99={ma60*0.99:.2f}, low60×1.05={low60*1.05:.2f})"
            _SUPPORT_CACHE[code] = (now_ts, False, reason)
            return False, reason

        # 条件 2：量能不缩（动量判断企稳）
        if vol_ratio is None:
            # 量能获取失败，放行但记日志
            logger.warning(f'_check_left_side_support({code}) 量能获取失败，放行')
            _SUPPORT_CACHE[code] = (now_ts, True, f'✅ 价位在支撑区 + 量能获取失败（放行）')
            return True, f'✅ 价位在支撑区 + 量能获取失败（放行）'

        if vol_ratio < 0.6:  # 放宽阈值 0.8 → 0.6
            reason = f'🔍 量能过缩 (今日量={vol_ratio:.2f}×5日均)，无量阴跌不能买'
            _SUPPORT_CACHE[code] = (now_ts, False, reason)
            return False, reason

        # ⚡ 加分项
        if last_close > last_open and vol_ratio >= 1.0:
            reason = f'✅ 价位在支撑区 + 今日量比{vol_ratio:.2f}×收红 —— 启动信号'
            _SUPPORT_CACHE[code] = (now_ts, True, reason)
            return True, reason

        # 探低反弹：近 3 日有 low 创近 60 日新低但 close 阳线
        found = False
        for i in range(-3, 0):
            try:
                row = df.iloc[i]
                if (float(row['low']) <= low60 * 1.01 and
                    float(row['close']) > float(row['open'])):
                    found = True
                    break
            except IndexError:
                continue
        if found:
            reason = f'✅ 近 3 日有探低反弹日 + 量比{vol_ratio:.2f}×'
            _SUPPORT_CACHE[code] = (now_ts, True, reason)
            return True, reason

        reason = f'✅ 价位在支撑区但未见启动 (今日{"阳" if last_close>last_open else "阴"}，量比{vol_ratio:.2f}× — 等企稳'
        _SUPPORT_CACHE[code] = (now_ts, False, reason)
        return False, reason
    except Exception as e:
        logger.warning(f"_check_left_side_support({code}) failed: {e}")
        return False, f'检查异常: {e}'


def _check_trend_gate(rule: dict, action: str) -> tuple[bool, str]:
    """趋势过滤器，决定 signal 是否放行。"""
    gate = (rule.get('trend_filter') or {}).get('gate', 'auto')
    code = rule.get('code', '')
    tf = (rule.get('trend_filter') or {})

    if gate in ('frozen', 'manual_only'):
        return False, f'🚫 trend_filter={gate}'

    if gate == 'require_support':
        ok, reason = _check_left_side_support(code, tf)
        if not ok:
            return False, f'🔍 require_support — {reason}'
        return True, f'✅ require_support 检查通过: {reason}'

    if gate == 'wait_volume':
        vol_ok = _realtime_vol_ok(code)
        if vol_ok:
            return True, '⚡ trend_filter=wait_volume 但实时检查量能已放大，放行'
        return False, f'📊 trend_filter=wait_volume (量比{_get_today_vol_ratio(code) or "?"}×，等量能放大'

    if gate == 'wait_macd':
        macd_ok = _realtime_macd_ok(code)
        if macd_ok:
            return True, '⚡ trend_filter=wait_macd 但实时检查 MACD 已金叉，放行'
        return False, '⏳ trend_filter=wait_macd (MACD 未金叉，等右侧确认）'

    # auto 或其他
    return True, '✅ trend_filter 放行'


def _check_stop_loss_severity(code: str, rule: dict, cur_price: float, position: dict) -> tuple[str, str, str]:
    """P0 量价共振 + 收盘确认止损评级 + P2 跟踪止损。"""
    rule_stop = float(rule.get('trigger', 0) or 0)
    
    # P2: 读跟踪止损，与 rule_stop 取 max（最高那个最保护，即亏损最小）
    trailing_stop = 0.0
    trailing_reason = ''
    if position and position.get('trailing_stop_price'):
        trailing_stop = float(position['trailing_stop_price'])
    
    stop = max(rule_stop, trailing_stop)
    if trailing_stop > 0 and stop == trailing_stop and trailing_stop > rule_stop:
        trailing_reason = f' [跟踪止损¥{trailing_stop:.2f} 高于原¥{rule_stop:.2f}]'
    
    if stop <= 0 or cur_price > stop:
        return 'none', 'NO_ACTION', '未跌破止损价'
    
    is_trailing = trailing_stop > 0 and stop == trailing_stop and stop > rule_stop
    severity_prefix = '🎯 跟踪止损触发: ' if is_trailing else ''
    
    # ① 硬止损 — stop × 0.95
    if cur_price <= stop * 0.95:
        deeper_pct = (cur_price - stop) / stop * 100
        return 'hard', 'SELL_ALL', f'{severity_prefix}⛔️ 倒破 {abs(deeper_pct):.1f}% 进入硬止损区 (¥{cur_price:.2f} ≤ ¥{stop:.2f}×0.95=¥{stop*0.95:.2f})，清仓{trailing_reason}'
    
    # ②③ 取量能
    vol_ratio = _get_today_vol_ratio(code)
    is_late = _is_late_session()
    
    if vol_ratio is not None and vol_ratio >= _STOP_VOL_THRESH:
        return 'confirmed', 'SELL_HALF', f'{severity_prefix}📉 跌破¥{stop:.2f} 且量比{vol_ratio:.2f}× (≥{_STOP_VOL_THRESH}) — 放量下跌主力出货，减半{trailing_reason}'
    
    # 量能不足 — 软止损
    vol_desc = f'量比{vol_ratio:.2f}×' if vol_ratio is not None else '量能未知'
    if is_late:
        return 'confirmed', 'SELL_HALF', f'{severity_prefix}⏰ 近收盘仍跌破¥{stop:.2f} ({vol_desc})，避免拖到明天减半{trailing_reason}'
    # 盘中软止损
    return 'soft', 'DEFER', f'{severity_prefix}⚠️ 跌破¥{stop:.2f} 但 {vol_desc} 未放量，软预警 — 等尾盘检查是否反包{trailing_reason}'


def calc_trailing_stop(entry_price: float, highest_price: float, current_trailing: float | None = None) -> tuple[float, str]:
    """P2: 跟踪止损计算。只能上移，不能下移。"""
    if entry_price <= 0 or highest_price <= 0:
        return current_trailing or 0.0, ''
    
    profit_pct = (highest_price - entry_price) / entry_price * 100
    
    if profit_pct < 5.0:
        new_stop = current_trailing or 0.0
        reason = f'浮盈 {profit_pct:.1f}% < 5%, 跟踪止损未启动'
    elif profit_pct < 10.0:
        new_stop = round(entry_price * 1.0, 2)
        reason = f'赚过 5% → 保本位 ¥{new_stop:.2f}'
    elif profit_pct < 20.0:
        new_stop = round(entry_price * 1.02, 2)
        reason = f'赚过 10% → 锁 2% 利润 ¥{new_stop:.2f}'
    else:
        floor_a = entry_price * 1.10
        floor_b = highest_price * 0.92
        new_stop = round(max(floor_a, floor_b), 2)
        reason = f'赚过 20% → 跟踪高点 max(entry×1.10, high×0.92) = ¥{new_stop:.2f}'
    
    # 只能上移不能下移
    if current_trailing and current_trailing > new_stop:
        return current_trailing, f'保持现跟踪位 ¥{current_trailing:.2f} (新计算 ¥{new_stop:.2f} 低于现位，不下移)'
    return new_stop, reason


def update_position_trailing(account_id: int, code: str, current_price: float) -> dict:
    """P2: 更新仓位的 highest_price 和 trailing_stop_price。每次实时价格变动后调用。"""
    conn = sqlite3.connect(_DB_PATH)
    try:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT quantity, avg_cost, highest_price, trailing_stop_price "
            "FROM sim_positions WHERE account_id=? AND stock_code=?",
            (account_id, code)
        ).fetchone()
        if not row or row[0] <= 0:
            return {'updated': False, 'reason': '无持仓'}
        qty, avg_cost, prev_high, prev_trailing = row
        new_high = max(prev_high or avg_cost, current_price)
        new_trailing, reason = calc_trailing_stop(avg_cost, new_high, prev_trailing)
        cur.execute(
            "UPDATE sim_positions SET highest_price=?, trailing_stop_price=? "
            "WHERE account_id=? AND stock_code=?",
            (new_high, new_trailing, account_id, code)
        )
        conn.commit()
        return {
            'updated': True,
            'highest': new_high,
            'trailing': new_trailing,
            'reason': reason,
        }
    finally:
        conn.close()


def decide_action(rule: dict, cur_price: float) -> str:
    """决策函数：根据 rule.level 决定 BUY / SELL_HALF / SELL_ALL / NO_ACTION。"""
    level = rule.get('level', '')
    code = rule.get('code', '')
    name = rule.get('name', '')
    trigger = float(rule.get('trigger', 0) or 0)
    direction = rule.get('dir', 'below')

    if level in ('buy_zone', 'buy_strong'):
        # 买入信号
        gate_ok, gate_reason = _check_trend_gate(rule, 'BUY')
        if not gate_ok:
            logger.info(f'🚫 [{code}] {level} 触发但趋势过滤未放行: {gate_reason}')
            return 'NO_ACTION'

        # 检查价格合理性
        ok, reason = check_price_sanity(code, cur_price, 'BUY')
        if not ok:
            logger.info(f'⚠️ [{code}] {level} 触发但价格检查失败: {reason}')
            return 'NO_ACTION'

        # 检查账户现金是否足够
        conn = sqlite3.connect(_DB_PATH)
        try:
            acct = conn.execute(
                "SELECT cash, total_value FROM sim_account WHERE id=?", (_ACCOUNT_ID,)
            ).fetchone()
            if not acct:
                return 'NO_ACTION'
            cash = float(acct[0])
            budget = min(DEFAULT_BUY_BUDGET, cash * 0.95)  # 最多用 95% 现金
            if budget < cur_price * LOT_SIZE:
                logger.info(f'⚠️ [{code}] {level} 触发但现金不足: ¥{cash:.0f}')
                return 'NO_ACTION'
        finally:
            conn.close()

        return 'BUY'

    elif level in ('stop_loss', 'soft_stop', 'hard_stop', 'deep_drop'):
        severity, sev_action, sev_reason = _check_stop_loss_severity(code, rule, cur_price, None)
        return sev_action  # NO_ACTION / SELL_HALF / SELL_ALL / DEFER

    elif level in ('take_profit', 'half_out'):
        return 'SELL_HALF'

    return 'NO_ACTION'


def execute_trade(rule: dict, cur_price: float) -> dict:
    """持仓股止损止盈。
    
    返回: {'updated': bool, 'highest': float, 'trailing': float, 'reason': str}
    """
    code = rule["code"]
    name = rule["name"]
    action = decide_action(rule, cur_price)
    severity = None
    severity_label = ''
    
    # 🔥 P0+P2: 智能止损三档评级 + 跟踪止损 — 只对 stop_loss 类 level 作修正
    stop_levels = {'stop_loss', 'soft_stop', 'hard_stop', 'deep_drop'}
    severity_msg = ''
    if rule.get('level') in stop_levels:
        # P2: 先拉仓位，拿 trailing_stop_price
        position = None
        try:
            conn = sqlite3.connect(_DB_PATH)
            row = conn.execute(
                "SELECT quantity, avg_cost, highest_price, trailing_stop_price "
                "FROM sim_positions WHERE account_id=? AND stock_code=?",
                (_ACCOUNT_ID, code)
            ).fetchone()
            conn.close()
            if row and row[0] > 0:
                position = {
                    'quantity': row[0],
                    'avg_cost': row[1],
                    'highest_price': row[2],
                    'trailing_stop_price': row[3],
                }
                # P2: 先更新跟踪止损（钉住高点、抬高止损位）
                update_position_trailing(_ACCOUNT_ID, code, cur_price)
                # 重拉拿最新的 trailing_stop_price
                conn = sqlite3.connect(_DB_PATH)
                row2 = conn.execute(
                    "SELECT highest_price, trailing_stop_price "
                    "FROM sim_positions WHERE account_id=? AND stock_code=?",
                    (_ACCOUNT_ID, code)
                ).fetchone()
                conn.close()
                if row2:
                    position['highest_price'] = row2[0]
                    position['trailing_stop_price'] = row2[1]
        except Exception as e:
            logger.warning(f"拉仓位/更新跟踪失败 {code}: {e}")
        
        severity, sev_action, sev_reason = _check_stop_loss_severity(code, rule, cur_price, position)
        severity_msg = sev_reason
        # 修正 action：SELL_HALF/SELL_ALL 以 severity 为准
        if sev_action in ('SELL_HALF', 'SELL_ALL'):
            action = sev_action
            logger.info(f"🔥 止损评级={severity}: {sev_reason}")

    if action == 'NO_ACTION':
        return {'action': action, 'success': True, 'message': '仅提醒，不操作', 'trade': None,
                'severity': severity, 'severity_label': severity_label}

    if action == 'DEFER':
        return {'action': action, 'success': True, 'message': f'软止损预警（不自动卖): {severity_msg}',
                'trade': None, 'severity': severity, 'severity_label': severity_label}

    if action == 'BUY':
        # 执行买入
        budget = DEFAULT_BUY_BUDGET
        qty = int(budget / cur_price / LOT_SIZE) * LOT_SIZE
        if qty <= 0:
            return {'action': action, 'success': False, 'message': f'计算买入数量失败: budget={budget}, price={cur_price}'}

        conn = sqlite3.connect(_DB_PATH)
        try:
            conn.execute("BEGIN")
            acct = conn.execute(
                "SELECT cash, total_value FROM sim_account WHERE id=?", (_ACCOUNT_ID,)
            ).fetchone()
            if not acct or float(acct[0]) < cur_price * qty:
                conn.execute("ROLLBACK")
                return {'action': action, 'success': False, 'message': f'现金不足: ¥{acct[0] if acct else 0:.0f}'}

            commission = cur_price * qty * COMMISSION_RATE
            amount = cur_price * qty + commission

            conn.execute(
                "UPDATE sim_account SET cash=cash-?, total_value=total_value-? WHERE id=?",
                (amount, amount, _ACCOUNT_ID)
            )
            # 更新或插入仓位
            existing = conn.execute(
                "SELECT quantity, avg_cost FROM sim_positions WHERE account_id=? AND stock_code=?",
                (_ACCOUNT_ID, code)
            ).fetchone()
            if existing:
                new_qty = existing[0] + qty
                new_cost = (existing[0] * existing[1] + qty * cur_price) / new_qty
                conn.execute(
                    "UPDATE sim_positions SET quantity=?, avg_cost=?, current_price=?, market_value=?, pnl=?, pnl_pct=? "
                    "WHERE account_id=? AND stock_code=?",
                    (new_qty, new_cost, cur_price, new_qty * cur_price,
                     (cur_price - new_cost) * new_qty, (cur_price - new_cost) / new_cost * 100,
                     _ACCOUNT_ID, code)
                )
            else:
                conn.execute(
                    "INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (_ACCOUNT_ID, code, name, qty, cur_price, cur_price, qty * cur_price,
                     0.0, 0.0)
                )
            # 写入成交记录
            trade_date = datetime.now().strftime('%Y-%m-%d')
            trade_time = datetime.now().strftime('%H:%M:%S')
            conn.execute(
                "INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, stock_name, direction, price, quantity, amount, commission) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_ACCOUNT_ID, trade_date, trade_time, code, name, 'BUY', cur_price, qty, amount, commission)
            )
            conn.execute("COMMIT")
            logger.info(f"✅ [{code}] {name} BUY {qty}股 @¥{cur_price:.2f}, 金额¥{amount:.0f}")
            return {'action': action, 'success': True,
                    'message': f'买入 {qty}股 @¥{cur_price:.2f}',
                    'trade': {'direction': 'BUY', 'price': cur_price, 'quantity': qty, 'amount': amount}}
        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(f"买入执行失败 {code}: {e}")
            return {'action': action, 'success': False, 'message': f'买入执行失败: {e}'}
        finally:
            conn.close()

    if action in ('SELL_HALF', 'SELL_ALL'):
        # 执行卖出
        sell_qty = 0
        conn = sqlite3.connect(_DB_PATH)
        try:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT quantity, avg_cost FROM sim_positions WHERE account_id=? AND stock_code=?",
                (_ACCOUNT_ID, code)
            ).fetchone()
            if not row or row[0] <= 0:
                conn.execute("ROLLBACK")
                return {'action': action, 'success': False, 'message': f'无持仓可卖 {code}'}

            if action == 'SELL_HALF':
                sell_qty = int(row[0] / 2 / LOT_SIZE) * LOT_SIZE
            else:
                sell_qty = row[0]

            if sell_qty <= 0:
                conn.execute("ROLLBACK")
                return {'action': action, 'success': False, 'message': f'计算卖出数量失败'}

            commission = cur_price * sell_qty * COMMISSION_RATE
            stamp_tax = cur_price * sell_qty * STAMP_TAX_RATE
            amount = cur_price * sell_qty - commission - stamp_tax

            conn.execute(
                "UPDATE sim_account SET cash=cash+?, total_value=total_value+? WHERE id=?",
                (amount, amount, _ACCOUNT_ID)
            )
            new_qty = row[0] - sell_qty
            if new_qty > 0:
                new_cost = row[1]  # 剩余仓位成本不变
                conn.execute(
                    "UPDATE sim_positions SET quantity=?, current_price=?, market_value=?, pnl=?, pnl_pct=? "
                    "WHERE account_id=? AND stock_code=?",
                    (new_qty, cur_price, new_qty * cur_price,
                     (cur_price - new_cost) * new_qty, (cur_price - new_cost) / new_cost * 100,
                     _ACCOUNT_ID, code)
                )
            else:
                conn.execute(
                    "DELETE FROM sim_positions WHERE account_id=? AND stock_code=?",
                    (_ACCOUNT_ID, code)
                )
            # 写入成交记录
            trade_date = datetime.now().strftime('%Y-%m-%d')
            trade_time = datetime.now().strftime('%H:%M:%S')
            conn.execute(
                "INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, stock_name, direction, price, quantity, amount, commission) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_ACCOUNT_ID, trade_date, trade_time, code, name, 'SELL', cur_price, sell_qty, amount, commission)
            )
            conn.execute("COMMIT")
            logger.info(f"✅ [{code}] {name} SELL {sell_qty}股 @¥{cur_price:.2f}, 金额¥{amount:.0f}")
            return {'action': action, 'success': True,
                    'message': f'卖出 {sell_qty}股 @¥{cur_price:.2f}',
                    'trade': {'direction': 'SELL', 'price': cur_price, 'quantity': sell_qty, 'amount': amount}}
        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(f"卖出执行失败 {code}: {e}")
            return {'action': action, 'success': False, 'message': f'卖出执行失败: {e}'}
        finally:
            conn.close()

    return {'action': 'NO_ACTION', 'success': True, 'message': '未知 action', 'trade': None}


# ── CLI 入口 ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='sim_executor — 阈值触发自动虚拟下单')
    sub = parser.add_subparsers(dest='command')

    # buy
    p_buy = sub.add_parser('buy', help='执行买入')
    p_buy.add_argument('--code', required=True)
    p_buy.add_argument('--name', default='')
    p_buy.add_argument('--price', type=float, required=True)
    p_buy.add_argument('--level', default='buy_zone')
    p_buy.set_defaults(func=lambda args: print(json.dumps(execute_trade(
        {'code': args.code, 'name': args.name, 'level': args.level, 'trigger': args.price, 'dir': 'below'},
        args.price), ensure_ascii=False, indent=2)))

    # sell
    p_sell = sub.add_parser('sell', help='执行卖出')
    p_sell.add_argument('--code', required=True)
    p_sell.add_argument('--name', default='')
    p_sell.add_argument('--price', type=float, required=True)
    p_sell.add_argument('--level', default='stop_loss')
    p_sell.set_defaults(func=lambda args: print(json.dumps(execute_trade(
        {'code': args.code, 'name': args.name, 'level': args.level, 'trigger': args.price, 'dir': 'above'},
        args.price), ensure_ascii=False, indent=2)))

    # update_trailing
    p_trail = sub.add_parser('update_trailing', help='更新跟踪止损')
    p_trail.add_argument('--code', required=True)
    p_trail.add_argument('--price', type=float, required=True)
    p_trail.set_defaults(func=lambda args: print(json.dumps(
        update_position_trailing(_ACCOUNT_ID, args.code, args.price),
        ensure_ascii=False, indent=2)))

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)
