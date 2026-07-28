import warnings; warnings.warn('This module is DEPRECATED. Use scripts/quant_engine.py + quant_core/ instead.', DeprecationWarning, stacklevel=2)
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
import warnings
from datetime import datetime, time as _dt_time
from pathlib import Path
from typing import Optional

# ── 强制使用 live_mirror DB ─────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))
_DB_PATH = os.environ['QUANT_DB_PATH']

from sim.db import get_conn
from sim.precision import quantize_amount, quantize_cost, quantize_price

import logging

# ═══════════════════════════════════════════════════════════════════
# quant_core 适配桥接 — 逐步接入新核心，不破坏现有功能
# ═══════════════════════════════════════════════════════════════════
try:
    from quant_core.fees import FeeModel as _QCFeeModel, FeeConfig as _QCFeeConfig
    _HAS_QC_FEES = True
except ImportError:
    _HAS_QC_FEES = False

try:
    from quant_core.strategy import ThresholdStrategyCore as _QCThresholdStrategyCore
    from quant_core.strategy import PortfolioState as _QCPortfolioState
    _HAS_QC_STRATEGY = True
except ImportError:
    _HAS_QC_STRATEGY = False

try:
    from quant_core.execution import validate_execution_timing as _qc_validate_execution_timing
    from quant_core.execution import ExecutionPolicy as _QCExecutionPolicy
    from quant_core.execution import ExecutionConfig as _QCExecutionConfig
    _HAS_QC_EXECUTION = True
except ImportError:
    _HAS_QC_EXECUTION = False

try:
    from quant_core.risk import RiskEngine as _QCRiskEngine, RiskCheckResult as _QCRiskCheckResult
    from quant_core.risk import TradingHealthGate as _QCTradingHealthGate
    _HAS_QC_RISK = True
except ImportError:
    _HAS_QC_RISK = False

try:
    from quant_core.metrics import (
        calc_sharpe as _qc_calc_sharpe,
        calc_sortino as _qc_calc_sortino,
        calc_max_drawdown as _qc_calc_max_drawdown,
        calc_net_expectancy as _qc_calc_net_expectancy,
        calc_excess_return as _qc_calc_excess_return,
        calc_information_ratio as _qc_calc_information_ratio,
    )
    _HAS_QC_METRICS = True
except ImportError:
    _HAS_QC_METRICS = False

try:
    from quant_core.portfolio import (
        PortfolioConfig as _QCPortfolioConfig,
        calculate_position_size as _qc_calculate_position_size,
    )
    _HAS_QC_PORTFOLIO = True
except ImportError:
    _HAS_QC_PORTFOLIO = False

try:
    from quant_core.domain import (
        SignalIntent as _QCSignalIntent,
        OrderIntent as _QCOrderIntent,
        OrderSide as _QCOrderSide,
        Direction as _QCDirection,
        Fill as _QCFill,
        Bar as _QCBar,
    )
    _HAS_QC_DOMAIN = True
except ImportError:
    _HAS_QC_DOMAIN = False

logger = logging.getLogger(__name__)
logger = logging.getLogger(__name__)

# ============================================================
# 双账户架构（2026-05-22）
#   id=1 live_mirror    → 学习账户（自动下单）
#   id=2 real_portfolio → 真实账户（仅告警，不下单）
# ============================================================
_ACCOUNT_ID: int = int(os.environ.get('SIM_ACCOUNT_ID', '1'))


def _load_max_total() -> float:
    """从 config.yaml 读取学习账户总额上限，默认 100000。"""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
        return float((cfg.get('accounts') or {}).get('learn', {}).get('max_total_value', 100000.0))
    except Exception:
        return 100000.0


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
_MACD_CACHE_TTL_SEC = 600  # MACD/支撑检查缓存有效期（秒）
_MA20_CACHE = {}          # code → (timestamp, ma20_value)
_MA20_CACHE_TTL_SEC = 300  # MA20 缓存有效期 5 分钟
_MA20_MAX_DEVIATION_PCT = 5.0  # REQ-060: MA20偏离最大允许百分比

# TASK-20260709-2004-001: buy_zone 信号 MA10 偏移拦截阈值（≥该值拒绝执行）
_BUY_ZONE_MA10_MAX_DEVIATION_PCT = 5.0  # 超过此阈值拦截买入
_MA10_CACHE = {}          # code → (timestamp, ma10_value)
_MA10_CACHE_TTL_SEC = 300  # MA10 缓存有效期 5 分钟

def _ensure_trailing_columns(conn: sqlite3.Connection) -> None:
    """REQ-041: 旧 sim_positions 表幂等补齐跟踪止损字段。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sim_positions)").fetchall()}
    if "trailing_stop_price" not in cols:
        conn.execute("ALTER TABLE sim_positions ADD COLUMN trailing_stop_price REAL DEFAULT NULL")
    if "highest_price" not in cols:
        conn.execute("ALTER TABLE sim_positions ADD COLUMN highest_price REAL DEFAULT NULL")
    if "updated_at" not in cols:
        conn.execute("ALTER TABLE sim_positions ADD COLUMN updated_at TIMESTAMP")


# A股最小交易单位 100 股
LOT_SIZE = 100

# 默认每次买入的金额上限（避免一把梭）
DEFAULT_BUY_BUDGET = 10000   # 单次买入预算（单只约总资金 5-10%）

# 费率
COMMISSION_RATE = 0.00025   # 万2.5
STAMP_TAX_RATE = 0.0005   # 万5（仅卖出）

# ── quant_core 适配: 佣金计算桥接 ──────────────────────────────────
def calc_commission(amount: float, rate: float = COMMISSION_RATE) -> float:
    """计算佣金 — 桥接到 quant_core.fees.FeeModel。

    Deprecated: 请使用 quant_core.fees.FeeModel.calculate() 替代。
    """
    warnings.warn(
        "calc_commission is deprecated, use quant_core.fees.FeeModel.calculate() instead",
        DeprecationWarning, stacklevel=2,
    )
    if _HAS_QC_FEES:
        model = _QCFeeModel()
        fees = model.calculate(side="BUY", amount=amount)
        return fees.commission
    return max(amount * rate, 5.0)  # 旧逻辑保底


def calc_stamp_tax(amount: float) -> float:
    """计算印花税 — 桥接到 quant_core.fees.FeeModel。

    Deprecated: 请使用 quant_core.fees.FeeModel.calculate(side='SELL') 替代。
    """
    warnings.warn(
        "calc_stamp_tax is deprecated, use quant_core.fees.FeeModel.calculate(side='SELL') instead",
        DeprecationWarning, stacklevel=2,
    )
    if _HAS_QC_FEES:
        model = _QCFeeModel()
        fees = model.calculate(side="SELL", amount=amount)
        return fees.stamp_tax
    return amount * STAMP_TAX_RATE

# ── REQ-038 持仓数量硬上限（从 config.yaml 读取，缺省 6/2）─────────────────────
def _load_risk_limits():
    """从 config.yaml 读取风控上限，返回 (max_total, max_daily_new)."""
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
        risk = cfg.get('risk') or {}
        max_total = int(risk.get('max_total_positions', 6))
        max_daily = int(risk.get('max_daily_new_positions', 2))
        return max_total, max_daily
    except Exception:
        return 6, 2

MAX_TOTAL_POSITIONS, MAX_DAILY_NEW_POSITIONS = _load_risk_limits()


# ── REQ-036 行业集中度风控 ──────────────────────────────────────────────
_INDUSTRY_CACHE = {}       # code → (timestamp, industry)
_INDUSTRY_CACHE_TTL = 3600  # 行业分类缓存 1 小时
def _load_industry_concentration_limits():
    """从 config.yaml 读取行业集中度风控上限。
    支持两种配置格式：
    1. risk.industry_concentration (新格式, 优先)
    2. risk 下的旧字段 max_industry_pct, max_sector_pct (兼容)
    """
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
        risk = cfg.get('risk') or {}
        ic = risk.get('industry_concentration') or {}
        if ic:
            return {
                'enabled': bool(ic.get('enabled', True)),
                'max_single_pct': float(ic.get('max_single_industry_pct', 30.0)),
                'max_cross_count': int(ic.get('max_cross_industry_count', 3)),
            }
        # 兼容旧格式
        return {
            'enabled': True,
            'max_single_pct': float(risk.get('max_industry_pct', 0.3)) * 100,
            'max_cross_count': int(risk.get('max_cross_industry_count', 3)),
        }
    except Exception:
        return {'enabled': True, 'max_single_pct': 30.0, 'max_cross_count': 3}
_INDUSTRY_LIMITS = _load_industry_concentration_limits()


def _get_stock_industry(code: str) -> Optional[str]:
    """获取股票行业分类，使用 baostock 的 query_stock_industry。"""
    import time
    now = time.time()
    cached = _INDUSTRY_CACHE.get(code)
    if cached and (now - cached[0]) < _INDUSTRY_CACHE_TTL:
        return cached[1]
    try:
        import baostock as bs
        bs.login()
        try:
            rs = bs.query_stock_industry(code)
            if rs.error_code == '0':
                rows = []
                while rs.next():
                    rows.append(rs.get_row_data())
                if rows:
                    # 返回最新的一条行业分类
                    ind = rows[0][-1] if len(rows[0]) > 0 else None
                    _INDUSTRY_CACHE[code] = (now, ind)
                    return ind
        finally:
            bs.logout()
    except Exception as e:
        logger.debug(f'获取行业 {code} 失败: {e}')
    _INDUSTRY_CACHE[code] = (now, None)
    return None


def _check_industry_concentration(conn: sqlite3.Connection, account_id: int,
                                   code: str, total_value: float) -> tuple[bool, str]:
    """REQ-036: 检查行业集中度是否超限。
    
    1. 如果该股票属于已有持仓的行业，检查该行业总市值占比是否超 max_single_pct
    2. 如果是全新行业，检查已覆盖行业数是否超 max_cross_count
    """
    if not _INDUSTRY_LIMITS['enabled']:
        return True, '行业集中度检查已禁用'
    
    # 获取目标股票的行业
    target_ind = _get_stock_industry(code)
    if not target_ind:
        return True, f'无法获取 {code} 行业分类，放行'
    
    max_single_pct = _INDUSTRY_LIMITS['max_single_pct']
    max_cross = _INDUSTRY_LIMITS['max_cross_count']
    
    # 统计持仓中各行业的市值占比
    rows = conn.execute("""
        SELECT stock_code, stock_name, market_value
        FROM sim_positions
        WHERE account_id = ? AND quantity > 0
    """, (account_id,)).fetchall()
    
    if not rows:
        # 无持仓，允许买入
        return True, f'无现有持仓，行业={target_ind or "未知"}，放行'
    
    # 计算每个行业的市值占比
    # 注意：批量获取行业可能较慢，这里逐股获取并缓存
    industry_mv = {}  # industry → total market_value
    for row in rows:
        stock_code = row[0]
        mv = float(row[2] or 0)
        ind = _get_stock_industry(stock_code)
        if ind:
            industry_mv[ind] = industry_mv.get(ind, 0) + mv
    
    # 检查目标行业是否已存在
    existing_mv = industry_mv.get(target_ind, 0)
    existing_pct = (existing_mv / total_value * 100) if total_value > 0 else 0
    
    if existing_pct >= max_single_pct:
        reason = (f'行业"{target_ind}"集中度过高: 现有占比{existing_pct:.1f}% ≥ 上限{max_single_pct}%，'
                  f'拒绝新建 {code}')
        return False, reason
    
    # 检查跨行业数量
    current_industry_count = len(industry_mv)
    # 如果目标行业不在现有持仓中，算作新增行业
    if target_ind not in industry_mv:
        if current_industry_count >= max_cross:
            reason = (f'已覆盖{current_industry_count}个行业 ≥ 上限{max_cross}，'
                      f'行业"{target_ind}"为新行业，拒绝新建 {code}')
            return False, reason
    
    return True, (f'行业"{target_ind}"集中度{existing_pct:.1f}% < {max_single_pct}%，'
                  f'跨行业{current_industry_count}/{max_cross}，通过')



# ── BUG-009：同一股票同日买入去重 ─────────────────────────────────────────
def _today_str() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _has_today_buy(conn: sqlite3.Connection, code: str) -> bool:
    """同一账户/股票/交易日是否已有 BUY 成交。

    阈值执行器可能在同一轮里同时收到 buy_zone、buy_strong 等多级信号。
    这里在执行层做最终幂等保护，避免重复加仓突破仓位约束。
    """
    row = conn.execute(
        """
        SELECT 1 FROM sim_trades
         WHERE account_id=? AND stock_code=? AND direction='BUY' AND trade_date=?
         LIMIT 1
        """,
        (_ACCOUNT_ID, code, _today_str()),
    ).fetchone()
    return row is not None


def _has_today_sell(conn: sqlite3.Connection, code: str) -> bool:
    """BUG-011: 同一账户/股票/交易日是否已有 SELL 成交。

    同日反向交易防御：若今日已卖出，则当日不允许再买入同一股票，
    防止 buy_strong + trend_break 同日矛盾信号导致自成交/瞬时反向。
    """
    row = conn.execute(
        """
        SELECT 1 FROM sim_trades
         WHERE account_id=? AND stock_code=? AND direction='SELL' AND trade_date=?
         LIMIT 1
        """,
        (_ACCOUNT_ID, code, _today_str()),
    ).fetchone()
    return row is not None


# ── TASK-20260705-0215-004：近期止损冷却期 ─────────────────────────────────────
def _has_recent_stop_loss(conn: sqlite3.Connection, code: str, lookback_days: int = 5) -> bool:
    """检查该股票在最近 N 天内是否有 BUY+SELL 成对出现（即买入即止损的信号质量差模式）。

    如果最近 lookback_days 天内该股票出现过同日或相邻日的 BUY→SELL，
    说明该股信号质量差，应暂缓买入。默认 5 天冷却期（涵盖周末/节假日）。
    """
    today = _today_str()
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT trade_date) FROM sim_trades
         WHERE account_id=? AND stock_code=?
           AND trade_date >= date(?, '-' || ? || ' days')
           AND trade_date < ?
           AND direction IN ('BUY', 'SELL')
         GROUP BY trade_date
         HAVING COUNT(DISTINCT direction) >= 2
        """,
        (_ACCOUNT_ID, code, today, lookback_days, today),
    ).fetchone()
    return row is not None and row[0] > 0


def _write_review_decision(account_id: int, stock_code: str, decision_type: str,
                           allowed: int, reason: str):
    """写入 review_decisions 表留痕；兼容 allowed/action、有无 trade_date 等旧表结构。

    TASK-20260702-2004-005 修复：添加去重/限流机制，避免冷静期产生大量无效日志。
    """
    try:
        conn = sqlite3.connect(_DB_PATH)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS review_decisions ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  account_id INTEGER NOT NULL,"
            "  stock_code TEXT NOT NULL,"
            "  trade_date DATE NOT NULL DEFAULT (date('now', 'localtime')),"
            "  decision_type TEXT NOT NULL,"
            "  allowed INTEGER NOT NULL,"
            "  reason TEXT,"
            "  created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))"
            ")"
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(review_decisions)").fetchall()}
        today = _today_str()
        has_trade_date = "trade_date" in cols
        has_created_at = "created_at" in cols

        # ── TASK-20260702-2004-005: 去重/限流（缺列则降级，仍要能写入）──
        if allowed == 0:
            if has_trade_date:
                existing = conn.execute(
                    "SELECT 1 FROM review_decisions "
                    "WHERE account_id=? AND stock_code=? AND trade_date=? AND decision_type=? "
                    "LIMIT 1",
                    (account_id, stock_code, today, decision_type),
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT 1 FROM review_decisions "
                    "WHERE account_id=? AND stock_code=? AND decision_type=? "
                    "LIMIT 1",
                    (account_id, stock_code, decision_type),
                ).fetchone()
            if existing:
                conn.close()
                return
        elif has_created_at:
            if has_trade_date:
                existing = conn.execute(
                    "SELECT 1 FROM review_decisions "
                    "WHERE account_id=? AND stock_code=? AND trade_date=? AND decision_type=? "
                    "  AND created_at >= datetime('now', 'localtime', '-5 minutes') "
                    "LIMIT 1",
                    (account_id, stock_code, today, decision_type),
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT 1 FROM review_decisions "
                    "WHERE account_id=? AND stock_code=? AND decision_type=? "
                    "  AND created_at >= datetime('now', 'localtime', '-5 minutes') "
                    "LIMIT 1",
                    (account_id, stock_code, decision_type),
                ).fetchone()
            if existing:
                conn.close()
                return

        if "allowed" in cols:
            if has_trade_date:
                conn.execute(
                    "INSERT INTO review_decisions "
                    "(account_id, stock_code, trade_date, decision_type, allowed, reason) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (account_id, stock_code, today, decision_type, allowed, reason),
                )
            else:
                conn.execute(
                    "INSERT INTO review_decisions (account_id, stock_code, decision_type, allowed, reason) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (account_id, stock_code, decision_type, allowed, reason),
                )
        elif "action" in cols:
            if has_trade_date:
                conn.execute(
                    "INSERT INTO review_decisions "
                    "(account_id, stock_code, trade_date, decision_type, action, reason) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (account_id, stock_code, today, decision_type, allowed, reason),
                )
            else:
                conn.execute(
                    "INSERT INTO review_decisions (account_id, stock_code, decision_type, action, reason) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (account_id, stock_code, decision_type, allowed, reason),
                )
        else:
            logger.warning("_write_review_decision: review_decisions 无 allowed/action 列，跳过写入")
            conn.close()
            return
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"_write_review_decision 失败: {e}")


def _load_daily_buy_controls() -> tuple[float, float, int]:
    """REQ-033: 从 config.yaml 读取日内买入资金预算与冷静期。

    返回 (daily_amount_cap, daily_pct_cap, cooldown_minutes)：
    - daily_amount_cap: 当日 BUY 成交额硬上限；默认 30,000 元
    - daily_pct_cap: 当日 BUY 成交额占账户总资产上限；默认 35%
    - cooldown_minutes: 任意两次自动 BUY 的最小间隔；默认 30 分钟
    """
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        risk = cfg.get('risk') or {}
        daily_amount_cap = float(
            risk.get('max_daily_buy_amount', risk.get('max_daily_trade_amount', 30000.0))
        )
        daily_pct_cap = float(risk.get('max_daily_buy_pct', risk.get('max_daily_build_amount_pct', 0.35)))
        cooldown_minutes = int(risk.get('buy_cooldown_minutes', 30))
        return daily_amount_cap, daily_pct_cap, cooldown_minutes
    except Exception:
        return 30000.0, 0.35, 30


MAX_DAILY_BUY_AMOUNT, MAX_DAILY_BUY_PCT, BUY_COOLDOWN_MINUTES = _load_daily_buy_controls()


# ============================================================
# TASK-20260702-2004-004: 买入后止损保护期
#   问题：buy_strong 买入后同日 trend_break 止损卖出
#   解决：买入后 N 分钟内不触发 trend_break/stop_loss 等止损信号
#   不改策略参数，只在执行层面加保护
# ============================================================
def _load_post_buy_protection() -> tuple[int, float]:
    """从 config.yaml 读取买入后保护参数。

    返回 (protect_minutes, protect_loss_pct)：
    - protect_minutes: 买入后多长时间内不触发止损（默认 120 分钟）
    - protect_loss_pct: 保护期内允许的最大亏损百分比，超过此值仍触发止损
      设为 0 或负数表示禁止止损；默认 -8%（与 risk.stop_loss_pct 对齐）
    """
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        risk = cfg.get('risk') or {}
        pb = risk.get('post_buy_protection') or {}
        protect_minutes = int(pb.get('protect_minutes', 120))
        # Prefer explicit post_buy override; else fall back to stop_loss_pct * 100.
        if 'protect_loss_pct' in pb:
            protect_loss_pct = float(pb.get('protect_loss_pct'))
        else:
            stop_pct = float(risk.get('stop_loss_pct', -0.08))
            protect_loss_pct = stop_pct * 100.0 if abs(stop_pct) <= 1.0 else stop_pct
        return protect_minutes, protect_loss_pct
    except Exception:
        return 120, -8.0


POST_BUY_PROTECT_MINUTES, POST_BUY_PROTECT_LOSS_PCT = _load_post_buy_protection()

# 受保护期内抑制的信号类型
_POST_BUY_SUPPRESS_LEVELS = frozenset({
    'stop_loss', 'stop_loss_tight', 'soft_stop', 'hard_stop', 'deep_drop',
    'trend_break', 'trend_break_warn',
})


def _load_stop_exit_controls() -> tuple[float, bool, bool]:
    """Load hard-stop / buy_strong gates from config.yaml.

    Returns:
        stop_loss_pct: fraction e.g. -0.08
        hard_stop_bypasses_same_day: allow same-day exit when hard stop / -8% hit
        buy_strong_enabled: whether buy_strong entries may execute
    """
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        risk = cfg.get('risk') or {}
        stop_loss_pct = float(risk.get('stop_loss_pct', -0.08))
        if abs(stop_loss_pct) > 1.0:
            stop_loss_pct = stop_loss_pct / 100.0
        bypass = bool(risk.get('hard_stop_bypasses_same_day', True))
        buy_strong_enabled = bool(risk.get('buy_strong_enabled', False))
        return stop_loss_pct, bypass, buy_strong_enabled
    except Exception:
        return -0.08, True, False


STOP_LOSS_PCT, HARD_STOP_BYPASSES_SAME_DAY, BUY_STRONG_ENABLED = _load_stop_exit_controls()


def _load_money_gates() -> tuple[float, bool, float, float]:
    """赚钱闸参数：单票仓位 / 大盘熔断 / 浮亏禁加仓。

    Returns:
        max_position_pct, market_panic_enabled, index_drop_pct, block_add_to_loser_pct
    """
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        risk = cfg.get('risk') or {}
        max_pos = float(risk.get('max_position_pct', 0.15))
        panic_on = bool(risk.get('market_panic_enabled', True))
        drop_pct = float(risk.get('market_panic_index_drop_pct', -1.0))
        loser_pct = float(risk.get('block_add_to_loser_pct', -3.0))
        return max_pos, panic_on, drop_pct, loser_pct
    except Exception:
        return 0.15, True, -1.0, -3.0


MAX_POSITION_PCT, MARKET_PANIC_ENABLED, MARKET_PANIC_DROP_PCT, BLOCK_ADD_TO_LOSER_PCT = (
    _load_money_gates()
)


def _planned_buy_shares(cash: float, cur_price: float) -> int:
    """按默认预算估算计划买入股数（100 股整数倍）。"""
    if cur_price <= 0:
        return 0
    budget = min(DEFAULT_BUY_BUDGET, cash * 0.95)
    qty = int(budget / cur_price / LOT_SIZE) * LOT_SIZE
    if qty < LOT_SIZE:
        qty = int(cash * 0.95 / cur_price / LOT_SIZE) * LOT_SIZE
    return max(qty, 0)


def _cap_budget_by_position_pct(
    conn: sqlite3.Connection,
    account_id: int,
    code: str,
    cur_price: float,
    budget: float,
) -> tuple[float, str]:
    """用单票仓位上限裁剪买入预算。返回 (裁剪后预算, 说明)。"""
    if cur_price <= 0 or MAX_POSITION_PCT <= 0:
        return budget, '仓位上限跳过'
    acct = conn.execute(
        "SELECT total_value FROM sim_account WHERE id=?", (account_id,)
    ).fetchone()
    total_value = float(acct[0]) if acct else 0.0
    if total_value <= 0:
        return budget, '账户总值无效，跳过仓位裁剪'
    row = conn.execute(
        "SELECT quantity FROM sim_positions WHERE account_id=? AND stock_code=? AND quantity > 0",
        (account_id, code),
    ).fetchone()
    existing_qty = int(row[0]) if row else 0
    existing_mv = existing_qty * cur_price
    max_mv = total_value * MAX_POSITION_PCT
    room = max_mv - existing_mv
    if room < cur_price * LOT_SIZE:
        return 0.0, (
            f'单票仓位已满：现有¥{existing_mv:.0f} + 一手 > 上限'
            f'{MAX_POSITION_PCT:.0%}×¥{total_value:.0f}=¥{max_mv:.0f}'
        )
    capped = min(budget, room)
    return capped, (
        f'单票仓位裁剪：预算¥{budget:.0f}→¥{capped:.0f}'
        f'（上限{MAX_POSITION_PCT:.0%}，剩余空间¥{room:.0f}）'
    )


def _load_scale_out_and_trailing() -> dict:
    """Load half take-profit + ATR trailing knobs from config.yaml."""
    defaults = {
        'take_profit_mode': 'half',
        'scale_out_enabled': True,
        'scale_out_at_r': 1.0,
        'scale_out_min_qty': 200,
        'scale_out_allow_same_day': True,
        'trailing_mode': 'atr_hybrid',
        'trailing_activate_pct': 5.0,
        'trailing_atr_mult': 2.0,
        'trailing_default_atr_pct': 3.0,
    }
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        risk = cfg.get('risk') or {}
        so = risk.get('scale_out') or {}
        tr = risk.get('trailing') or {}
        mode = str(risk.get('take_profit_mode', defaults['take_profit_mode']) or 'half').lower()
        if mode not in ('half', 'full'):
            mode = 'half'
        return {
            'take_profit_mode': mode,
            'scale_out_enabled': bool(so.get('enabled', True)),
            'scale_out_at_r': float(so.get('at_r', 1.0)),
            'scale_out_min_qty': int(so.get('min_qty', 200)),
            'scale_out_allow_same_day': bool(so.get('allow_same_day', True)),
            'trailing_mode': str(tr.get('mode', 'atr_hybrid') or 'atr_hybrid').lower(),
            'trailing_activate_pct': float(tr.get('activate_profit_pct', 5.0)),
            'trailing_atr_mult': float(tr.get('atr_mult', 2.0)),
            'trailing_default_atr_pct': float(tr.get('default_atr_pct', 3.0)),
        }
    except Exception:
        return defaults


_SCALE_TRAIL = _load_scale_out_and_trailing()
TAKE_PROFIT_MODE = _SCALE_TRAIL['take_profit_mode']
SCALE_OUT_ENABLED = _SCALE_TRAIL['scale_out_enabled']
SCALE_OUT_AT_R = _SCALE_TRAIL['scale_out_at_r']
SCALE_OUT_MIN_QTY = _SCALE_TRAIL['scale_out_min_qty']
SCALE_OUT_ALLOW_SAME_DAY = _SCALE_TRAIL['scale_out_allow_same_day']
TRAILING_MODE = _SCALE_TRAIL['trailing_mode']
TRAILING_ACTIVATE_PCT = _SCALE_TRAIL['trailing_activate_pct']
TRAILING_ATR_MULT = _SCALE_TRAIL['trailing_atr_mult']
TRAILING_DEFAULT_ATR_PCT = _SCALE_TRAIL['trailing_default_atr_pct']

# Cache watchlist atr_pct lookups
_ATR_PCT_CACHE: dict[str, float | None] = {}


def _get_atr_pct_for_code(code: str) -> float | None:
    """Read atr_pct from watchlist trend_filter.

    atr_hybrid: only use ATR when the stock has a known atr (else ladder-only).
    atr mode: fall back to trailing.default_atr_pct.
    """
    code = str(code or '')
    if code in _ATR_PCT_CACHE:
        return _ATR_PCT_CACHE[code]
    atr: float | None = None
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        wl = ((cfg.get('watchlist') or {}).get('user_manual') or {})
        item = wl.get(code) or {}
        tf = item.get('trend_filter') or {}
        if tf.get('atr_pct'):
            atr = float(tf['atr_pct'])
        elif tf.get('atr_stop_pct'):
            atr = float(tf['atr_stop_pct']) / 2.0
    except Exception:
        atr = None
    if atr is None and TRAILING_MODE in ('atr', 'atr_hybrid'):
        atr = TRAILING_DEFAULT_ATR_PCT
    _ATR_PCT_CACHE[code] = atr  # may cache None
    return atr


# ============================================================
# REQ-092: 买入前估值过滤
#   在买入信号执行前，结合PE(TTM)/PB/估值分位等指标过滤信号
#   避免在估值过高时买入
#   配置来源: config.local.yaml → valuation_filter
# ============================================================
def _load_valuation_filter_config() -> dict:
    """REQ-092: 从 config.yaml (merged with config.local.yaml) 读取估值过滤配置。

    返回 dict，包含：
    - enabled: 是否启用
    - max_pe_ttm: PE(TTM)绝对上限
    - max_pe_industry_ratio: PE/行业均值倍数上限
    - max_pe_percentile: PE历史分位上限(%)
    - max_pb: PB绝对上限
    - min_pb: PB下限
    - skip_negative_pe: 亏损股是否跳过过滤
    - cache_ttl_seconds: 缓存时间(秒)
    - timeout_seconds: API超时(秒)
    """
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}
        local_file = ROOT / 'config.local.yaml'
        if local_file.exists():
            local_cfg = yaml.safe_load(local_file.read_text(encoding='utf-8')) or {}
            _deep_merge(cfg, local_cfg)
        vf = (cfg.get('valuation_filter') or {})
        return {
            'enabled': bool(vf.get('enabled', True)),
            'max_pe_ttm': float(vf.get('max_pe_ttm', 100.0)),
            'max_pe_industry_ratio': float(vf.get('max_pe_industry_ratio', 2.0)),
            'max_pe_percentile': float(vf.get('max_pe_percentile', 80.0)),
            'max_pb': float(vf.get('max_pb', 10.0)),
            'min_pb': float(vf.get('min_pb', 0.0)),
            'skip_negative_pe': bool(vf.get('skip_negative_pe', True)),
            'cache_ttl_seconds': int(vf.get('cache_ttl_seconds', 600)),
            'timeout_seconds': int(vf.get('timeout_seconds', 10)),
        }
    except Exception as e:
        logger.warning(f'_load_valuation_filter_config 失败，使用默认配置: {e}')
        return {
            'enabled': True,
            'max_pe_ttm': 100.0,
            'max_pe_industry_ratio': 2.0,
            'max_pe_percentile': 80.0,
            'max_pb': 10.0,
            'min_pb': 0.0,
            'skip_negative_pe': True,
            'cache_ttl_seconds': 600,
            'timeout_seconds': 10,
        }


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个 dict（override 覆盖 base）。"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


# 估值缓存
_VALUATION_CACHE: dict[str, tuple[float, dict]] = {}  # code → (timestamp, {pe_ttm, pb, ...})


def _get_tencent_valuation(code: str, timeout: int = 10) -> dict | None:
    """REQ-092: 通过腾讯财经 API 获取个股 PE(TTM)/PB/市值等估值数据。

    数据来源：腾讯财经个股行情（§1.2 of a-stock-data SKILL）
    返回: {'name', 'price', 'pe_ttm', 'pb', 'market_cap', 'amount'} 或 None
    """
    import time as _time
    import requests as _requests

    now_ts = _time.time()
    cfg = _load_valuation_filter_config()
    ttl = cfg.get('cache_ttl_seconds', 600)

    # 检查缓存
    cached = _VALUATION_CACHE.get(code)
    if cached and (now_ts - cached[0]) < ttl:
        return cached[1]

    try:
        # 确定交易所前缀：6=上海，0/3=深圳，8/4=北交所
        prefix = 'sh' if code.startswith('6') else ('sz' if code.startswith(('0', '3')) else ('bj' if code.startswith(('8', '4')) else 'sh'))
        url = f'https://qt.gtimg.cn/q={prefix}{code}'
        resp = _requests.get(url, timeout=timeout, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://finance.qq.com/',
        })
        resp.encoding = 'gbk'
        text = resp.text

        # 腾讯格式: v_sh600519="1~贵州茅台~...~pe_ttm~pb~..."
        if '~' not in text or text.strip().startswith('pv_none'):
            logger.warning(f'_get_tencent_valuation({code}): 无数据返回')
            _VALUATION_CACHE[code] = (now_ts, None)
            return None

        parts = text.split('~')
        if len(parts) < 47:
            logger.warning(f'_get_tencent_valuation({code}): 返回数据字段不足')
            _VALUATION_CACHE[code] = (now_ts, None)
            return None

        result = {
            'name': parts[1] if len(parts) > 1 else '',
            'price': float(parts[3]) if parts[3].replace('.', '').replace('-', '').isdigit() else None,
            'pe_ttm': float(parts[39]) if len(parts) > 39 and parts[39].replace('.', '').replace('-', '').isdigit() else None,
            'pb': float(parts[46]) if len(parts) > 46 and parts[46].replace('.', '').replace('-', '').isdigit() else None,
            'market_cap': float(parts[45]) if len(parts) > 45 and parts[45].replace('.', '').replace('-', '').isdigit() else None,
            'amount': float(parts[37]) if len(parts) > 37 and parts[37].replace('.', '').replace('-', '').isdigit() else None,
        }
        _VALUATION_CACHE[code] = (now_ts, result)
        return result
    except Exception as e:
        logger.warning(f'_get_tencent_valuation({code}) 异常: {e}')
        _VALUATION_CACHE[code] = (now_ts, None)
        return None


def _check_valuation_filter(code: str, rule: dict) -> tuple[bool, str, dict]:
    """REQ-092: 买入前估值过滤检查。

    通过腾讯财经 API 获取 PE(TTM)/PB，按配置规则判断估值是否合理。

    返回 (allowed, reason, valuation_data)：
    - allowed: True=估值合理可买入, False=估值过高拒绝
    - reason: 过滤原因说明
    - valuation_data: 估值数据 dict，供 review_decisions 记录

    过滤规则（按优先级）：
    1. 配置 disabled → 放行
    2. PE为负(亏损) 且 skip_negative_pe=true → 放行
    3. PE > max_pe_ttm → 拒绝
    4. PB > max_pb → 拒绝
    5. PB < min_pb → 可选拒绝（破净检查）
    6. （PE分位/行业对比功能后续迭代实现）
    7. 数据获取失败 → 放行（不让数据问题阻断交易）
    """
    cfg = _load_valuation_filter_config()
    if not cfg.get('enabled', True):
        return True, '估值过滤已关闭', {}

    # 获取估值数据
    val = _get_tencent_valuation(code, timeout=cfg.get('timeout_seconds', 10))
    if val is None:
        # 数据获取失败，放行（不因数据问题阻断）
        return True, '估值数据获取失败，放行', {'status': 'data_unavailable'}

    pe_ttm = val.get('pe_ttm')
    pb = val.get('pb')
    stock_name = val.get('name', code)
    cur_price = val.get('price')
    market_cap = val.get('market_cap')

    valuation_data = {
        'pe_ttm': pe_ttm,
        'pb': pb,
        'price': cur_price,
        'market_cap': market_cap,
        'name': stock_name,
        'status': 'checking',
    }

    # Rule 1: PE为负（亏损），且配置允许跳过
    if pe_ttm is not None and pe_ttm <= 0:
        if cfg.get('skip_negative_pe', True):
            reason = f'PE为负(亏损): PE={pe_ttm}，配置允许跳过估值过滤'
            valuation_data['status'] = 'negative_pe_skipped'
            return True, reason, valuation_data
        else:
            reason = f'PE为负(亏损): PE={pe_ttm}，估值过滤拒绝（配置不允许亏损股）'
            valuation_data['status'] = 'negative_pe_rejected'
            return False, reason, valuation_data

    # Rule 2: PE过高
    if pe_ttm is not None:
        max_pe = cfg.get('max_pe_ttm', 100.0)
        if pe_ttm > max_pe:
            reason = f'PE过高: PE(TTM)={pe_ttm:.1f} > {max_pe}，估值过滤拒绝'
            valuation_data['status'] = 'pe_too_high'
            return False, reason, valuation_data

    # Rule 3: PB过高
    if pb is not None:
        max_pb = cfg.get('max_pb', 10.0)
        if pb > max_pb:
            reason = f'PB过高: PB={pb:.2f} > {max_pb}，估值过滤拒绝'
            valuation_data['status'] = 'pb_too_high'
            return False, reason, valuation_data

    # Rule 4: PB过低（破净检查，默认关闭 min_pb=0）
    min_pb = cfg.get('min_pb', 0.0)
    if min_pb > 0 and pb is not None and pb < min_pb:
        reason = f'PB过低(破净): PB={pb:.2f} < {min_pb}，估值过滤拒绝'
        valuation_data['status'] = 'pb_too_low'
        return False, reason, valuation_data

    # 通过所有检查
    pe_str = f'{pe_ttm:.1f}' if pe_ttm is not None else 'N/A'
    pb_str = f'{pb:.2f}' if pb is not None else 'N/A'
    reason = f'估值合理: PE(TTM)={pe_str}, PB={pb_str}'
    valuation_data['status'] = 'passed'
    return True, reason, valuation_data


def _get_last_buy_time(conn: sqlite3.Connection, code: str, account_id: int) -> datetime | None:
    """获取某股票在该账户最后一次 BUY 成交的时间。表缺失时返回 None（不挡卖）。"""
    try:
        row = conn.execute(
            """
            SELECT trade_date, trade_time FROM sim_trades
             WHERE account_id=? AND stock_code=? AND direction='BUY'
             ORDER BY trade_date DESC, COALESCE(trade_time, '00:00:00') DESC, id DESC
             LIMIT 1
            """,
            (account_id, code),
        ).fetchone()
    except sqlite3.OperationalError as e:
        logger.warning("_get_last_buy_time 跳过（DB不完整）: %s", e)
        return None
    if not row:
        return None
    return _parse_trade_datetime(row[0], row[1])


def _get_position_avg_cost(conn: sqlite3.Connection, code: str, account_id: int) -> float:
    """获取持仓平均成本。"""
    row = conn.execute(
        "SELECT avg_cost FROM sim_positions "
        "WHERE account_id=? AND stock_code=? AND quantity > 0",
        (account_id, code),
    ).fetchone()
    return float(row[0]) if row else 0.0


def _is_protected_by_post_buy(
    conn: sqlite3.Connection, code: str, level: str, cur_price: float,
    account_id: int | None = None
) -> tuple[bool, str]:
    """REQ-2004-004: 检查是否处于买入后止损保护期内。

    如果最近一次买入距现在不足 protect_minutes 分钟，且：
    - level 属于止损类信号（stop_loss/trend_break 等）
    - 当前浮亏未超过 protect_loss_pct（默认 -8%）
    则抑制卖出，返回 (True, reason)。
    """
    if POST_BUY_PROTECT_MINUTES <= 0:
        return False, ''  # 保护期设为 0 表示不启用

    if level not in _POST_BUY_SUPPRESS_LEVELS:
        return False, ''  # 非止损类信号，不抑制

    # Explicit hard_stop / deep_drop always pierce protection once price is at/below stop.
    if level in ('hard_stop', 'deep_drop'):
        avg_cost = _get_position_avg_cost(conn, code, int(account_id or _ACCOUNT_ID))
        if avg_cost > 0:
            loss_pct = (cur_price - avg_cost) / avg_cost * 100
            threshold_pct = STOP_LOSS_PCT * 100.0
            if loss_pct <= threshold_pct:
                return False, ''
            # hard_stop level even without full -8% still pierces soft protection window
            # only when protect_loss_pct already breached — fall through to normal check.

    account_id = int(account_id or _ACCOUNT_ID)
    last_buy = _get_last_buy_time(conn, code, account_id)
    if last_buy is None:
        return False, ''

    minutes_since_buy = (datetime.now() - last_buy).total_seconds() / 60.0
    if minutes_since_buy >= POST_BUY_PROTECT_MINUTES:
        return False, ''

    # 已进入保护期 — 检查是否属于灾难性暴跌（超过 protect_loss_pct）
    avg_cost = _get_position_avg_cost(conn, code, account_id)
    if avg_cost > 0:
        loss_pct = (cur_price - avg_cost) / avg_cost * 100
        if loss_pct <= POST_BUY_PROTECT_LOSS_PCT:
            # 亏损超过保护期紧急阈值，仍允许止损
            return False, ''
    else:
        loss_pct = None

    loss_str = f"（浮亏 {loss_pct:.1f}%）" if loss_pct is not None else ""
    reason = (
        f"🛡️ 买入后保护期: 距买入 {minutes_since_buy:.0f} 分钟 < {POST_BUY_PROTECT_MINUTES} 分钟，"
        f"抑制 {level} 止损信号{loss_str}（保护阈值 {POST_BUY_PROTECT_LOSS_PCT:.0f}%）"
    )
    return True, reason


def _cost_loss_pct(conn: sqlite3.Connection, code: str, cur_price: float,
                   account_id: int | None = None) -> float | None:
    """Return unrealized loss percent vs avg_cost, or None if no cost basis."""
    avg_cost = _get_position_avg_cost(conn, code, int(account_id or _ACCOUNT_ID))
    if avg_cost <= 0 or cur_price <= 0:
        return None
    return (cur_price - avg_cost) / avg_cost * 100.0


def _same_day_hard_stop_allowed(
    conn: sqlite3.Connection, code: str, cur_price: float, level: str,
    account_id: int | None = None,
) -> tuple[bool, str]:
    """Whether same-day sell may proceed despite today's BUY.

    Soft exits (trend_break / early take-profit fluff) stay blocked. Hard cost
    breach at ``STOP_LOSS_PCT``, explicit ``hard_stop``/``deep_drop``, or
    configured +R scale-out / take-profit may exit.
    """
    if not HARD_STOP_BYPASSES_SAME_DAY and not SCALE_OUT_ALLOW_SAME_DAY:
        return False, ''

    level = str(level or '')
    if HARD_STOP_BYPASSES_SAME_DAY and level in ('hard_stop', 'deep_drop'):
        return True, f'硬止损 level={level} 允许同日卖出'

    loss_pct = _cost_loss_pct(conn, code, cur_price, account_id)
    if loss_pct is None:
        return False, ''

    threshold_pct = STOP_LOSS_PCT * 100.0
    if HARD_STOP_BYPASSES_SAME_DAY and loss_pct <= threshold_pct:
        return True, f'成本浮亏 {loss_pct:.2f}% ≤ 硬止损 {threshold_pct:.1f}%，允许同日卖出'

    # +R scale-out / take-profit half may bank winners same day.
    if SCALE_OUT_ALLOW_SAME_DAY and level in (
        'take_profit', 'take_profit_half', 'half_out', 'scale_out',
    ):
        target_pct = abs(STOP_LOSS_PCT) * 100.0 * float(SCALE_OUT_AT_R)
        if loss_pct >= target_pct:  # loss_pct is signed; profit is positive
            return True, f'浮盈 {loss_pct:.2f}% ≥ +{SCALE_OUT_AT_R:.1f}R ({target_pct:.1f}%)，允许同日半仓止盈'
    return False, ''


def _has_sell_since_last_buy(
    conn: sqlite3.Connection, code: str, account_id: int | None = None,
) -> bool:
    """True if any SELL exists after the latest BUY for this code (already scaled/stopped)."""
    account_id = int(account_id or _ACCOUNT_ID)
    last_buy = conn.execute(
        "SELECT id FROM sim_trades WHERE account_id=? AND stock_code=? AND direction='BUY' "
        "ORDER BY trade_date DESC, id DESC LIMIT 1",
        (account_id, code),
    ).fetchone()
    if not last_buy:
        return False
    row = conn.execute(
        "SELECT COUNT(*) FROM sim_trades WHERE account_id=? AND stock_code=? AND direction='SELL' "
        "AND id > ?",
        (account_id, code, last_buy[0]),
    ).fetchone()
    return bool(row and row[0] > 0)


def _scale_out_target_price(avg_cost: float) -> float:
    """Price at +scale_out_at_r * R, where R = |stop_loss_pct|."""
    r = abs(float(STOP_LOSS_PCT))
    return float(avg_cost) * (1.0 + float(SCALE_OUT_AT_R) * r)


def _check_cost_scale_out(
    conn: sqlite3.Connection,
    code: str,
    cur_price: float,
    quantity: int,
    avg_cost: float,
    account_id: int | None = None,
) -> tuple[bool, str]:
    """Cost-based +1R half take-profit when qty allows a lot-sized half."""
    if not SCALE_OUT_ENABLED or TAKE_PROFIT_MODE != 'half':
        return False, ''
    if quantity < SCALE_OUT_MIN_QTY:
        return False, ''
    half_qty = int(quantity / 2 / LOT_SIZE) * LOT_SIZE
    if half_qty < LOT_SIZE:
        return False, ''
    if avg_cost <= 0 or cur_price <= 0:
        return False, ''
    if _has_sell_since_last_buy(conn, code, account_id):
        return False, ''
    target = _scale_out_target_price(avg_cost)
    if cur_price + 1e-9 < target:
        return False, ''
    profit_pct = (cur_price - avg_cost) / avg_cost * 100.0
    return True, (
        f'scale_out|+{SCALE_OUT_AT_R:.1f}R 半仓止盈: 现价¥{cur_price:.2f} ≥ '
        f'目标¥{target:.2f}（成本¥{avg_cost:.2f} 浮盈{profit_pct:.1f}%）'
    )


def _parse_trade_datetime(trade_date: str | None, trade_time: str | None) -> datetime | None:
    """兼容 sim_trades 中 trade_date=YYYY-MM-DD、trade_time=HH:MM:SS/空 的格式。"""
    if not trade_date:
        return None
    raw = f"{trade_date} {trade_time or '00:00:00'}"
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            pass
    return None


def get_daily_buy_budget_status(account_id: int | None = None, planned_amount: float = 0.0) -> dict:
    """REQ-033: 返回当日自动买入预算状态，供复盘/看板展示。"""
    account_id = int(account_id or _ACCOUNT_ID)
    today = _today_str()
    conn = sqlite3.connect(_DB_PATH)
    try:
        try:
            acct = conn.execute(
                "SELECT cash, total_value, initial_cash FROM sim_account WHERE id=?",
                (account_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            acct = conn.execute(
                "SELECT cash, total_value FROM sim_account WHERE id=?",
                (account_id,),
            ).fetchone()
            if acct:
                acct = (acct[0], acct[1], acct[1])
        total_value = float((acct[1] if acct and acct[1] else 0) or (acct[2] if acct and len(acct) > 2 and acct[2] else 0) or _load_max_total())
        pct_cap_amount = total_value * MAX_DAILY_BUY_PCT if MAX_DAILY_BUY_PCT > 0 else MAX_DAILY_BUY_AMOUNT
        daily_cap = min(MAX_DAILY_BUY_AMOUNT, pct_cap_amount) if MAX_DAILY_BUY_AMOUNT > 0 else pct_cap_amount
        used = float(conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM sim_trades "
            "WHERE account_id=? AND direction='BUY' AND trade_date=?",
            (account_id, today),
        ).fetchone()[0] or 0.0)
        last = conn.execute(
            "SELECT trade_date, trade_time, stock_code FROM sim_trades "
            "WHERE account_id=? AND direction='BUY' "
            "ORDER BY trade_date DESC, COALESCE(trade_time, '00:00:00') DESC, id DESC LIMIT 1",
            (account_id,),
        ).fetchone()
        last_dt = _parse_trade_datetime(last[0], last[1]) if last else None
        minutes_since_last = None
        if last_dt:
            minutes_since_last = max(0.0, (datetime.now() - last_dt).total_seconds() / 60.0)
        remaining = max(0.0, daily_cap - used)
        return {
            'date': today,
            'account_id': account_id,
            'daily_cap': daily_cap,
            'used': used,
            'remaining': remaining,
            'planned_amount': planned_amount,
            'after_planned': used + max(0.0, planned_amount),
            'cooldown_minutes': BUY_COOLDOWN_MINUTES,
            'minutes_since_last_buy': minutes_since_last,
            'last_buy_code': last[2] if last else None,
        }
    finally:
        conn.close()


def _check_daily_buy_controls(conn: sqlite3.Connection, account_id: int, code: str, planned_amount: float) -> tuple[bool, str, dict]:
    """REQ-033: 日内新买入资金预算 + 连续买入冷静期检查。

    注意：使用调用方传入的 conn 读取 sim_trades，可在 execute_trade 的
    BEGIN IMMEDIATE 事务内完成最终校验，避免并发/重算预算穿透。
    """
    account_id = int(account_id)
    today = _today_str()
    try:
        acct = conn.execute(
            "SELECT cash, total_value, initial_cash FROM sim_account WHERE id=?",
            (account_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        acct = conn.execute(
            "SELECT cash, total_value FROM sim_account WHERE id=?",
            (account_id,),
        ).fetchone()
        if acct:
            acct = (acct[0], acct[1], acct[1])
    total_value = float((acct[1] if acct and acct[1] else 0) or (acct[2] if acct and len(acct) > 2 and acct[2] else 0) or _load_max_total())
    pct_cap_amount = total_value * MAX_DAILY_BUY_PCT if MAX_DAILY_BUY_PCT > 0 else MAX_DAILY_BUY_AMOUNT
    daily_cap = min(MAX_DAILY_BUY_AMOUNT, pct_cap_amount) if MAX_DAILY_BUY_AMOUNT > 0 else pct_cap_amount
    used = float(conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM sim_trades "
        "WHERE account_id=? AND direction='BUY' AND trade_date=?",
        (account_id, today),
    ).fetchone()[0] or 0.0)
    last = conn.execute(
        "SELECT trade_date, trade_time, stock_code FROM sim_trades "
        "WHERE account_id=? AND direction='BUY' "
        "ORDER BY trade_date DESC, COALESCE(trade_time, '00:00:00') DESC, id DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    last_dt = _parse_trade_datetime(last[0], last[1]) if last else None
    minutes_since_last = None
    if last_dt:
        minutes_since_last = max(0.0, (datetime.now() - last_dt).total_seconds() / 60.0)
    remaining = max(0.0, daily_cap - used)
    status = {
        'date': today,
        'account_id': account_id,
        'daily_cap': daily_cap,
        'used': used,
        'remaining': remaining,
        'planned_amount': planned_amount,
        'after_planned': used + max(0.0, planned_amount),
        'cooldown_minutes': BUY_COOLDOWN_MINUTES,
        'minutes_since_last_buy': minutes_since_last,
        'last_buy_code': last[2] if last else None,
    }
    after = status['after_planned']
    if daily_cap > 0 and after > daily_cap + 1e-6:
        return False, (
            f"日内买入预算不足：今日已用¥{used:,.0f}，计划¥{planned_amount:,.0f}，"
            f"将达¥{after:,.0f} > 上限¥{daily_cap:,.0f}；剩余¥{status['remaining']:,.0f}"
        ), status

    # TASK-20260707-000600: 同一标的近20日内曾止损 → 加再入场冷却期
    recent_stop = conn.execute(
        "SELECT trade_date FROM sim_trades "
        "WHERE account_id=? AND stock_code=? AND direction='SELL' "
        "  AND (signal_reason LIKE '%stop_loss%' OR signal_reason LIKE '%trend_break%') "
        "  AND trade_date >= date('now','-20 days') "
        "ORDER BY trade_date DESC LIMIT 1",
        (account_id, code),
    ).fetchone()
    if recent_stop:
        return False, (
            f"止损冷却期拦截：{code} 近20日({recent_stop[0]})曾触发止损(trend_break/stop_loss)，"
            f"暂停买入以观察信号质量；今日剩余预算¥{status['remaining']:,.0f}"
        ), status

    mins = status.get('minutes_since_last_buy')
    last_buy_code = status.get('last_buy_code')
    # REQ-062: 冷静期改为同股冷却 — 只有同一只股票才需要等待冷却期
    if BUY_COOLDOWN_MINUTES > 0 and mins is not None and mins < BUY_COOLDOWN_MINUTES and last_buy_code == code:
        return False, (
            f"同股买入冷静期未过：距上次买入 {code} {mins:.0f} 分钟 < {BUY_COOLDOWN_MINUTES} 分钟，"
            f"跳过；今日剩余买入预算¥{status['remaining']:,.0f}"
        ), status

    return True, (
        f"日内买入预算通过：今日已用¥{used:,.0f}/¥{daily_cap:,.0f}，"
        f"本次约¥{planned_amount:,.0f}，剩余约¥{max(0.0, daily_cap-after):,.0f}"
    ), status


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
    warnings.warn(
        "check_price_sanity is deprecated, use quant_core.execution.ExecutionPolicy.validate() instead",
        DeprecationWarning, stacklevel=2,
    )
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
        # REQ-049 修复：只警告不阻断，允许买入（可能是开盘前检查）
        if abs(cur_price - yc) < 0.005:
            return True, f"⚠️ 价格 {cur_price:.2f} == 昨收价 {yc:.2f}，疑似伪实时价，已放行"

    elif action.startswith('SELL'):
        floor = yc * (1 - limit_pct * 0.95)
        if cur_price <= floor:
            return False, f"价格 {cur_price:.2f} 接近跌停阈 {floor:.2f}（昨收 {yc:.2f} -{limit_pct*100:.0f}%），拒卖出"

    return True, "价格合理"


def _is_late_session() -> bool:
    """是否近收盘（14:40 后）。REQ-046: 从 14:50 提前到 14:40，给软止损升级留时间。"""
    now = datetime.now()
    return (now.hour > 14) or (now.hour == 14 and now.minute >= 40)


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
    
    REQ-049 修复：放宽条件，提高买入信号执行率：
    1. 价格支撑：在 MA60 附近不破 或 在近 60 日低点企稳 或 5日均线拐头向上
    2. 量能企稳：今日量 ≥ 近 5 日均量 × 0.4（进一步放宽从 0.6 → 0.4）
    3. 量能获取失败时放行（不因数据问题阻断信号）
    ⚡ 加分（其中一项满足即可）：
      - 今日收红（close > open）且量比 ≥ 0.8 —— 启动信号（放宽从 1.0）
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

        if len(rows) < 30:  # REQ-049: 降低数据要求 60→30，允许更多股票通过
            _SUPPORT_CACHE[code] = (now_ts, True, '数据不足30日，放行（REQ-049）')
            return True, '数据不足30日，放行（REQ-049）'

        df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume'])
        for c in ['open','high','low','close','volume']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna()

        last_close = float(df['close'].iloc[-1])
        last_open = float(df['open'].iloc[-1])
        last_low = float(df['low'].iloc[-1])
        ma5 = float(df['close'].tail(5).mean()) if len(df) >= 5 else last_close
        ma60 = float(df['close'].tail(60).mean()) if len(df) >= 60 else last_close
        low60 = float(df['low'].tail(60).min()) if len(df) >= 60 else last_low
        avg_vol5 = float(df['volume'].tail(5).mean()) if len(df) >= 5 else 0
        today_vol = float(df['volume'].iloc[-1])
        vol_ratio = (today_vol / avg_vol5) if avg_vol5 > 0 else None

        # 条件 1：价格支撑（REQ-049: 增加 MA5 拐头条件）
        near_ma60 = last_close >= ma60 * 0.97  # REQ-049: 放宽 0.99→0.97
        near_low60 = last_close <= low60 * 1.08  # REQ-049: 放宽 1.05→1.08
        # 新增：5日均线拐头向上也算支撑
        ma5_turning_up = False
        if len(df) >= 6:
            ma5_prev = float(df['close'].iloc[-6:-1].tail(5).mean())
            ma5_turning_up = ma5 > ma5_prev and last_close > ma5
        price_ok = near_ma60 or near_low60 or ma5_turning_up
        if not price_ok:
            reason = f"🔍 价位未见企稳 (MA60×0.97={ma60*0.97:.2f}, low60×1.08={low60*1.08:.2f}, MA5拐头={'是' if ma5_turning_up else '否'})"
            _SUPPORT_CACHE[code] = (now_ts, False, reason)
            return False, reason

        # 条件 2：量能不缩（REQ-049: 大幅放宽阈值 0.6 → 0.4）
        if vol_ratio is None:
            logger.warning(f'_check_left_side_support({code}) 量能获取失败，放行')
            _SUPPORT_CACHE[code] = (now_ts, True, f'✅ 价位在支撑区 + 量能获取失败（放行）')
            return True, f'✅ 价位在支撑区 + 量能获取失败（放行）'

        if vol_ratio < 0.4:  # REQ-049: 大幅放宽阈值 0.6→0.4
            reason = f'🔍 量能过缩 (今日量={vol_ratio:.2f}×5日均)，无量阴跌不能买'
            _SUPPORT_CACHE[code] = (now_ts, False, reason)
            return False, reason

        # ⚡ 加分项
        if last_close > last_open and vol_ratio >= 0.8:  # REQ-049: 放宽 1.0→0.8
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

        # REQ-049: 价格支撑OK + 量能不是极度萎缩 → 放行（以前会拒绝）
        reason = f'✅ 价位在支撑区 + 量比{vol_ratio:.2f}×（REQ-049: 放行）'
        _SUPPORT_CACHE[code] = (now_ts, True, reason)
        return True, reason
    except Exception as e:
        logger.warning(f"_check_left_side_support({code}) failed: {e}")
        # REQ-049: 检查异常时放行（不因数据获取问题阻断有效信号）
        return True, f'支撑检查异常，放行: {e}'


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
    
    # REQ-099/101/068: confirmed 止损一律 SELL_ALL。
    # 旧 SELL_HALF 会 900→400→200→100，剩 100 股半仓取整为 0 →「计算卖出数量失败」卡死。
    if vol_ratio is not None and vol_ratio >= _STOP_VOL_THRESH:
        return 'confirmed', 'SELL_ALL', f'{severity_prefix}📉 跌破¥{stop:.2f} 且量比{vol_ratio:.2f}× (≥{_STOP_VOL_THRESH}) — 放量下跌主力出货，清仓{trailing_reason}'
    
    # 量能不足 — 软止损；但价格已跌破止损位超过 1% 时升级为 confirmed
    vol_desc = f'量比{vol_ratio:.2f}×' if vol_ratio is not None else '量能未知'
    if is_late:
        return 'confirmed', 'SELL_ALL', f'{severity_prefix}⏰ 近收盘仍跌破¥{stop:.2f} ({vol_desc})，避免拖到明天，清仓{trailing_reason}'
    # 盘中：价格跌破 stop 但未放量 → 若跌破幅度>1% 则升级为 confirmed（不无限 defer）
    break_pct = (cur_price - stop) / stop * 100
    if break_pct < -1.0:
        return 'confirmed', 'SELL_ALL', f'{severity_prefix}⚠️ 跌破¥{stop:.2f} 达 {abs(break_pct):.1f}% 且 {vol_desc} 未放量，升级清仓（不无限等待）{trailing_reason}'
    # 刚跌破不久（<1%）且量能不足 → 仍可等待尾盘
    return 'soft', 'DEFER', f'{severity_prefix}⚠️ 跌破¥{stop:.2f} 但 {vol_desc} 未放量，软预警 — 等尾盘检查是否反包{trailing_reason}'


def calc_trailing_stop(
    entry_price: float,
    highest_price: float,
    current_trailing: float | None = None,
    atr_pct: float | None = None,
) -> tuple[float, str]:
    """P2: 跟踪止损计算。只能上移，不能下移。

    Ladder (legacy):
      <5% idle; ≥5% breakeven; ≥10% lock +2%; ≥20% max(entry×1.10, high×0.92)

    ATR hybrid (default when atr_pct given / trailing.mode=atr_hybrid):
      also trail high × (1 - atr_mult × atr_pct/100), floored at entry once activated.
    """
    if entry_price <= 0 or highest_price <= 0:
        return current_trailing or 0.0, ''

    profit_pct = (highest_price - entry_price) / entry_price * 100
    activate = float(TRAILING_ACTIVATE_PCT)

    if profit_pct < activate:
        new_stop = current_trailing or 0.0
        reason = f'浮盈 {profit_pct:.1f}% < {activate:.0f}%, 跟踪止损未启动'
    elif profit_pct < 10.0:
        new_stop = round(entry_price * 1.01, 2)
        reason = f'赚过 {activate:.0f}% → 锁 1% 利润 ¥{new_stop:.2f}'
    elif profit_pct < 20.0:
        new_stop = round(entry_price * 1.02, 2)
        reason = f'赚过 10% → 锁 2% 利润 ¥{new_stop:.2f}'
    else:
        floor_a = entry_price * 1.10
        floor_b = highest_price * 0.92
        new_stop = round(max(floor_a, floor_b), 2)
        reason = f'赚过 20% → 跟踪高点 max(entry×1.10, high×0.92) = ¥{new_stop:.2f}'

    # ATR hybrid: ratchet with high - k*ATR once activated.
    use_atr = TRAILING_MODE in ('atr', 'atr_hybrid') and atr_pct is not None and atr_pct > 0
    if use_atr and profit_pct >= activate:
        atr_stop = highest_price * (1.0 - float(TRAILING_ATR_MULT) * float(atr_pct) / 100.0)
        # Never give back below entry once trail is live.
        atr_stop = max(atr_stop, entry_price)
        atr_stop = round(atr_stop, 2)
        if atr_stop > new_stop:
            new_stop = atr_stop
            reason = (
                f'ATR跟踪 high¥{highest_price:.2f} - {TRAILING_ATR_MULT:.1f}×ATR({atr_pct:.2f}%) '
                f'= ¥{new_stop:.2f}'
            )
        elif TRAILING_MODE == 'atr':
            new_stop = atr_stop
            reason = (
                f'ATR跟踪 high¥{highest_price:.2f} - {TRAILING_ATR_MULT:.1f}×ATR({atr_pct:.2f}%) '
                f'= ¥{new_stop:.2f}'
            )

    # P2-BUGFIX: 确保已激活的跟踪止损至少覆盖成本价 + 1% 保护垫
    # 场景：ATR 止损被 floor 在 entry 或阶梯保本位 = entry，但浮盈已达激活条件，
    # 此时 trailing_stop 应至少为 entry * 1.01 以真正锁定利润而非原地踏保。
    if profit_pct >= activate:
        min_activated = round(entry_price * 1.005, 2)
        if new_stop > 0 and new_stop < min_activated:
            new_stop = min_activated
            reason = f'已激活 → 保本+垫 ¥{new_stop:.2f} (防 ATR 过宽/阶梯归本位原地踏保)'

    # 只能上移不能下移
    if current_trailing and current_trailing > new_stop:
        return current_trailing, f'保持现跟踪位 ¥{current_trailing:.2f} (新计算 ¥{new_stop:.2f} 低于现位，不下移)'
    return new_stop, reason


def update_position_trailing(account_id: int, code: str, current_price: float) -> dict:
    """P2: 更新仓位的 highest_price 和 trailing_stop_price。每次实时价格变动后调用。"""
    conn = sqlite3.connect(_DB_PATH)
    try:
        _ensure_trailing_columns(conn)
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
        atr_pct = _get_atr_pct_for_code(code) if TRAILING_MODE in ('atr', 'atr_hybrid') else None
        new_trailing, reason = calc_trailing_stop(avg_cost, new_high, prev_trailing, atr_pct=atr_pct)
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
            'atr_pct': atr_pct,
        }
    finally:
        conn.close()


def _recalc_account_total(conn: sqlite3.Connection, account_id: int) -> float:
    """REQ-069: total_value = cash + Σ market_value（quantity>0）。返回新 total。"""
    acct = conn.execute("SELECT cash FROM sim_account WHERE id=?", (account_id,)).fetchone()
    if not acct:
        return 0.0
    mv = conn.execute(
        "SELECT COALESCE(SUM(market_value),0) FROM sim_positions WHERE account_id=? AND quantity > 0",
        (account_id,),
    ).fetchone()[0] or 0.0
    total = quantize_amount(float(acct[0] or 0) + float(mv))
    conn.execute(
        "UPDATE sim_account SET total_value=? WHERE id=?",
        (total, account_id),
    )
    return total


def update_all_positions_market_value(price_dict: dict, account_id: int | None = None) -> int:
    """批量更新持仓现价/市值，并同步 REQ-041 跟踪止损。

    portfolio_alert 在每次行情刷新后调用它，让 trailing_stop_price 随价格抬高。
    返回实际更新的持仓数。
    """
    account_id = int(account_id or _ACCOUNT_ID)
    conn = sqlite3.connect(_DB_PATH)
    try:
        _ensure_trailing_columns(conn)
        updated = 0
        for code, raw_price in (price_dict or {}).items():
            try:
                cur_price = quantize_price(float(raw_price or 0))
            except Exception:
                continue
            if cur_price <= 0:
                continue
            row = conn.execute(
                "SELECT quantity, avg_cost, highest_price, trailing_stop_price "
                "FROM sim_positions WHERE account_id=? AND stock_code=? AND quantity > 0",
                (account_id, code),
            ).fetchone()
            if not row:
                continue
            qty, avg_cost, prev_high, prev_trailing = row
            new_high = max(float(prev_high or avg_cost or 0), cur_price)
            atr_pct = _get_atr_pct_for_code(code) if TRAILING_MODE in ('atr', 'atr_hybrid') else None
            new_trailing, _reason = calc_trailing_stop(avg_cost, new_high, prev_trailing, atr_pct=atr_pct)
            conn.execute(
                "UPDATE sim_positions SET current_price=?, market_value=?, pnl=?, pnl_pct=?, "
                "highest_price=?, trailing_stop_price=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE account_id=? AND stock_code=?",
                (
                    cur_price,
                    quantize_amount(qty * cur_price),
                    quantize_amount((cur_price - avg_cost) * qty),
                    (cur_price - avg_cost) / avg_cost * 100 if avg_cost else 0,
                    new_high,
                    new_trailing if new_trailing > 0 else None,
                    account_id,
                    code,
                ),
            )
            updated += 1
        _recalc_account_total(conn, account_id)
        conn.commit()
        return updated
    finally:
        conn.close()


def _check_ma20_deviation(code: str, rule: dict, cur_price: float) -> tuple[bool, str]:
    """REQ-060: buy_strong 信号执行前验证当前 MA20 是否与信号生成时偏离过大。
    
    从 rule 的 message 中提取信号生成时的 MA20 参考值，重新获取当前 MA20，
    若价格与当前 MA20 偏离超过 _MA20_MAX_DEVIATION_PCT% 则拒绝执行。
    
    Returns:
        (ok, reason): ok=True 表示 MA20 新鲜可执行，False 表示偏离过大需跳过
    """
    import re, time
    
    msg = rule.get('message', '')
    # 匹配 "回踩 MA20(X)" 或类似模式提取引用的 MA20 值
    m = re.search(r'MA20\(([\d.]+)\)', msg)
    if not m:
        # 信号不包含 MA20 引用，无需检查
        return True, '信号不含MA20引用，跳过MA20偏离检查'
    
    ref_ma20 = float(m.group(1))
    
    # 检查当前价格与引用 MA20 的偏离
    deviation_pct = abs(cur_price - ref_ma20) / ref_ma20 * 100
    if deviation_pct <= _MA20_MAX_DEVIATION_PCT:
        return True, f'MA20偏离{deviation_pct:.1f}% ≤ {_MA20_MAX_DEVIATION_PCT}%，价格与信号MA20一致'
    
    # 偏离较大：重新获取当前 MA20 确认
    now_ts = time.time()
    cached = _MA20_CACHE.get(code)
    if cached and (now_ts - cached[0]) < _MA20_CACHE_TTL_SEC:
        current_ma20 = cached[1]
    else:
        try:
            import baostock as bs
            import pandas as pd
            from datetime import datetime, timedelta
            prefix = 'sh' if code.startswith('6') else 'sz'
            end = datetime.now().strftime('%Y-%m-%d')
            start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
            bs.login()
            try:
                rs = bs.query_history_k_data_plus(
                    f'{prefix}.{code}', 'date,close',
                    start_date=start, end_date=end, frequency='d', adjustflag='2'
                )
                rows = []
                while (rs.error_code == '0') and rs.next():
                    rows.append(rs.get_row_data())
            finally:
                bs.logout()
            if len(rows) < 20:
                logger.warning(f'REQ-060 [{code}] K线数据不足20日，无法验证MA20，放行')
                return True, 'K线数据不足无法验证MA20，放行'
            closes = [float(r[1]) for r in rows]
            current_ma20 = sum(closes[-20:]) / 20
            _MA20_CACHE[code] = (now_ts, current_ma20)
        except Exception as e:
            logger.warning(f'REQ-060 [{code}] 获取MA20失败: {e}，放行')
            return True, f'MA20获取失败({e})，放行'
    
    # 检查当前价格与实时 MA20 的偏离
    real_deviation = abs(cur_price - current_ma20) / current_ma20 * 100
    if real_deviation <= _MA20_MAX_DEVIATION_PCT:
        return True, f'实时MA20偏离{real_deviation:.1f}% ≤ {_MA20_MAX_DEVIATION_PCT}%（信号MA20={ref_ma20}已过期但当前合理）'
    
    # 偏离过大，拒绝
    reason = (f'REQ-060 MA20严重偏离: 信号MA20={ref_ma20}, 实时MA20={current_ma20:.2f}, '
              f'现价={cur_price}, 偏离={real_deviation:.1f}% > {_MA20_MAX_DEVIATION_PCT}%')
    logger.warning(f'🚫 [{code}] {reason}')
    return False, reason


def _check_buy_zone_ma_deviation(code: str, rule: dict, cur_price: float) -> tuple[bool, str]:
    """TASK-20260709 / REQ-105: buy_zone 执行前校验信号阈值新鲜度。

    daily_recalibrate 写 buy_zone.trigger = MA10。若校准漏扫观察池，trigger 会冻结
    （如天赐 47.66、莲花 11.75），而现价已贴合实时 MA10 → 旧逻辑「现价≈实时MA10 放行」
    会让脏 trigger 成交，台账表现为「触发阈值串价」。

    v4（2026-07-28）：
    - 先比 trigger vs 实时 MA10（阈值新鲜度），过期则拦截
    - 再比现价 vs 实时 MA10（是否真在买区）
    - 删掉「已过期但当前合理」旁路
    - 行情拉取失败时：|现价-trigger|/trigger > 8% 硬拦（fail-closed），否则放行
    """
    import time

    _FAIL_CLOSED_TRIGGER_PCT = 8.0  # 赚钱闸：脏 trigger 数据缺失时更严（原 15%）

    ref_ma10 = float(rule.get('trigger', 0) or 0)
    if ref_ma10 <= 0:
        return True, 'buy_zone trigger无效，跳过MA10偏离检查'

    price_vs_trigger = abs(cur_price - ref_ma10) / ref_ma10 * 100
    if price_vs_trigger <= _BUY_ZONE_MA10_MAX_DEVIATION_PCT:
        return True, (
            f'MA10偏离{price_vs_trigger:.1f}% ≤ {_BUY_ZONE_MA10_MAX_DEVIATION_PCT}%，'
            f'价格与信号MA10一致'
        )

    now_ts = time.time()
    cached = _MA10_CACHE.get(code)
    if cached and (now_ts - cached[0]) < _MA10_CACHE_TTL_SEC:
        current_ma10 = cached[1]
    else:
        try:
            import baostock as bs
            from datetime import datetime, timedelta
            prefix = 'sh' if code.startswith('6') else 'sz'
            end = datetime.now().strftime('%Y-%m-%d')
            start = (datetime.now() - timedelta(days=40)).strftime('%Y-%m-%d')
            bs.login()
            try:
                rs = bs.query_history_k_data_plus(
                    f'{prefix}.{code}', 'date,close',
                    start_date=start, end_date=end, frequency='d', adjustflag='2'
                )
                rows = []
                while (rs.error_code == '0') and rs.next():
                    rows.append(rs.get_row_data())
            finally:
                bs.logout()
            if len(rows) < 10:
                if price_vs_trigger > _FAIL_CLOSED_TRIGGER_PCT:
                    reason = (
                        f'REQ-105(buy_zone) K线不足且现价相对脏trigger偏离{price_vs_trigger:.1f}% '
                        f'(trigger={ref_ma10:.2f}, price={cur_price:.2f})，拦截'
                    )
                    logger.warning(f'🚫 [{code}] {reason}')
                    return False, reason
                logger.warning(
                    f'REQ-105(buy_zone) [{code}] K线不足，偏离{price_vs_trigger:.1f}%'
                    f'≤{_FAIL_CLOSED_TRIGGER_PCT}%，放行'
                )
                return True, 'K线数据不足无法验证MA10，放行'
            closes = [float(r[1]) for r in rows]
            current_ma10 = sum(closes[-10:]) / 10
            _MA10_CACHE[code] = (now_ts, current_ma10)
        except Exception as e:
            if price_vs_trigger > _FAIL_CLOSED_TRIGGER_PCT:
                reason = (
                    f'REQ-105(buy_zone) MA10获取失败且现价相对脏trigger偏离{price_vs_trigger:.1f}% '
                    f'(trigger={ref_ma10:.2f}, price={cur_price:.2f}): {e}，拦截'
                )
                logger.warning(f'🚫 [{code}] {reason}')
                return False, reason
            logger.warning(
                f'REQ-105(buy_zone) [{code}] 获取MA10失败: {e}，'
                f'偏离≤{_FAIL_CLOSED_TRIGGER_PCT}%，放行'
            )
            return True, f'MA10获取失败({e})，放行'

    # 关键：信号阈值相对实时 MA10 是否过期（脏 trigger 根因拦截）
    trigger_vs_ma = abs(ref_ma10 - current_ma10) / current_ma10 * 100
    if trigger_vs_ma > _BUY_ZONE_MA10_MAX_DEVIATION_PCT:
        reason = (
            f'REQ-105(buy_zone) 信号MA10过期: trigger={ref_ma10:.2f} vs 实时MA10={current_ma10:.2f} '
            f'({trigger_vs_ma:.1f}% > {_BUY_ZONE_MA10_MAX_DEVIATION_PCT}%)，拦截'
        )
        logger.warning(f'🚫 [{code}] {reason}')
        return False, reason

    # 次要：现价是否贴近实时 MA10（真正 buy_zone）
    price_vs_ma = abs(cur_price - current_ma10) / current_ma10 * 100
    if price_vs_ma > _BUY_ZONE_MA10_MAX_DEVIATION_PCT:
        reason = (
            f'REQ-105(buy_zone) 现价偏离实时MA10: price={cur_price:.2f}, MA10={current_ma10:.2f}, '
            f'偏离={price_vs_ma:.1f}% > {_BUY_ZONE_MA10_MAX_DEVIATION_PCT}%'
        )
        logger.warning(f'🚫 [{code}] {reason}')
        return False, reason

    return True, (
        f'实时MA10新鲜(trigger={ref_ma10:.2f}≈{current_ma10:.2f})，'
        f'现价偏离{price_vs_ma:.1f}% ≤ {_BUY_ZONE_MA10_MAX_DEVIATION_PCT}%'
    )


def decide_action(rule: dict, cur_price: float, position: dict = None) -> str:
    warnings.warn(
        "decide_action is deprecated, use quant_core.strategy.ThresholdStrategyCore.decide() instead",
        DeprecationWarning, stacklevel=2,
    )
    """决策函数：根据 rule.level 决定 BUY / SELL_HALF / SELL_ALL / NO_ACTION。
    
    REQ-048 修复：添加 position 参数，传递给 _check_stop_loss_severity()
    """
    level = rule.get('level', '')
    code = rule.get('code', '')
    name = rule.get('name', '')
    trigger = float(rule.get('trigger', 0) or 0)
    direction = rule.get('dir', 'below')

    if level in ('buy_zone', 'buy_strong'):

        # Pause buy_strong until config re-enables it (edge sample was weak).
        if level == 'buy_strong' and not BUY_STRONG_ENABLED:
            reason = 'buy_strong 已暂停（risk.buy_strong_enabled=false），仅执行 buy_zone'
            logger.info(f'🚫 [{code}] {reason}')
            _write_review_decision(_ACCOUNT_ID, code, 'buy_strong_disabled', 0, reason)
            return 'NO_ACTION'

        # ── REQ-038 持仓数量硬上限检查 ─────────────────────────────────────
        # 1) 总持仓数上限
        conn = sqlite3.connect(_DB_PATH)
        try:
            total_pos = conn.execute(
                "SELECT COUNT(*) FROM sim_positions WHERE account_id=? AND quantity > 0",
                (_ACCOUNT_ID,)
            ).fetchone()[0]
        finally:
            conn.close()
        if total_pos >= MAX_TOTAL_POSITIONS:
            reason = f'总持仓数({total_pos})≥上限({MAX_TOTAL_POSITIONS})，拒绝新建 {code}'
            logger.info(f'🚫 [{code}] {reason}')
            _write_review_decision(_ACCOUNT_ID, code, 'position_count_limit', 0, reason)
            return 'NO_ACTION'

        # 2) 单日新建仓位数上限（只限制"新买入"，已有仓位加仓不受影响）
        conn = sqlite3.connect(_DB_PATH)
        try:
            # 检查是否已有持仓
            existing = conn.execute(
                "SELECT quantity FROM sim_positions WHERE account_id=? AND stock_code=? AND quantity > 0",
                (_ACCOUNT_ID, code)
            ).fetchone()
            if not existing:
                # 是新建仓位，检查今日已新建数量
                from datetime import datetime
                today = datetime.now().strftime('%Y-%m-%d')
                new_today = conn.execute(
                    "SELECT COUNT(DISTINCT stock_code) FROM sim_trades "
                    "WHERE account_id=? AND direction='BUY' AND trade_date=?",
                    (_ACCOUNT_ID, today)
                ).fetchone()[0]
                if new_today >= MAX_DAILY_NEW_POSITIONS:
                    reason = f'今日新建仓位({new_today})≥上限({MAX_DAILY_NEW_POSITIONS})，拒绝新建 {code}'
                    logger.info(f'🚫 [{code}] {reason}')
                    _write_review_decision(_ACCOUNT_ID, code, 'daily_new_position_limit', 0, reason)
                    return 'NO_ACTION'
        finally:
            conn.close()


        # 买入信号
        # REQ-049 修复：buy_strong/buy_zone 信号穿透 trend_gate（只记日志不阻断）
        # 理由：趋势过滤不应完全阻断已触发信号，仅 frozen/manual_only 才硬阻断
        gate_ok, gate_reason = _check_trend_gate(rule, 'BUY')
        if not gate_ok:
            if gate_reason and 'frozen' in gate_reason:
                # frozen/manual_only 是用户显式冻结，仍硬阻断
                logger.info(f'🚫 [{code}] {level} 触发但趋势过滤冻结: {gate_reason}')
                return 'NO_ACTION'
            else:
                # wait_volume/wait_macd/require_support 等软过滤：穿透，记日志
                logger.info(f'⚠️ [{code}] {level} 信号穿透 trend_gate: {gate_reason}（继续执行买入）')

        # 检查价格合理性
        ok, reason = check_price_sanity(code, cur_price, 'BUY')
        if not ok:
            logger.info(f'⚠️ [{code}] {level} 触发但价格检查失败: {reason}')
            return 'NO_ACTION'

        # ── REQ-060 buy_strong MA20新鲜度检查 ────────────────────
        if level == 'buy_strong':
            ma_ok, ma_reason = _check_ma20_deviation(code, rule, cur_price)
            if not ma_ok:
                logger.info(f'⚠️ [{code}] {level} MA20偏离过大: {ma_reason}')
                _write_review_decision(_ACCOUNT_ID, code, 'ma20_deviation_blocked', 0, ma_reason)
                return 'NO_ACTION'
            logger.info(f'✅ [{code}] {level} MA20检查通过: {ma_reason}')

        # ── TASK-20260709-2004-001 buy_zone MA10偏差拦截 ────────
        if level == 'buy_zone':
            ma_ok, ma_reason = _check_buy_zone_ma_deviation(code, rule, cur_price)
            if not ma_ok:
                logger.info(f'⚠️ [{code}] {level} MA10偏离过大: {ma_reason}')
                _write_review_decision(_ACCOUNT_ID, code, 'buy_zone_ma10_deviation_blocked', 0, ma_reason)
                return 'NO_ACTION'
            logger.info(f'✅ [{code}] {level} MA10检查通过: {ma_reason}')

        # ── 赚钱闸：弱势日禁买（REQ-028 大盘熔断，此前未接入 sim_executor）──
        if MARKET_PANIC_ENABLED:
            try:
                from vqlearn.services.buy_risk_guard import get_market_panic_decision
                panic = get_market_panic_decision()
                if panic.blocked:
                    logger.info(f'🚫 [{code}] 弱势日禁买: {panic.reason}')
                    _write_review_decision(
                        _ACCOUNT_ID, code, 'market_panic_blocked', 0, panic.reason
                    )
                    return 'NO_ACTION'
            except Exception as e:
                logger.warning(f'[{code}] 大盘熔断检查异常（放行）: {e}')

        # ── 赚钱闸：浮亏不加仓 ──
        conn = sqlite3.connect(_DB_PATH)
        try:
            loser_row = conn.execute(
                "SELECT quantity, pnl_pct FROM sim_positions "
                "WHERE account_id=? AND stock_code=? AND quantity > 0",
                (_ACCOUNT_ID, code),
            ).fetchone()
            if loser_row and float(loser_row[1] or 0) <= BLOCK_ADD_TO_LOSER_PCT:
                reason = (
                    f'浮亏不加仓：{code} 浮亏{float(loser_row[1]):.1f}% '
                    f'≤ {BLOCK_ADD_TO_LOSER_PCT:.1f}%'
                )
                logger.info(f'🚫 [{code}] {reason}')
                _write_review_decision(_ACCOUNT_ID, code, 'add_to_loser_blocked', 0, reason)
                return 'NO_ACTION'
        finally:
            conn.close()

        # 检查账户现金是否足够
        # REQ-049 修复：现金不足默认预算时，允许用全部现金买入（只要够买100股）
        conn = sqlite3.connect(_DB_PATH)
        try:
            acct = conn.execute(
                "SELECT cash, total_value FROM sim_account WHERE id=?", (_ACCOUNT_ID,)
            ).fetchone()
            if not acct:
                return 'NO_ACTION'
            cash = float(acct[0])
            # 预算 = min(默认单次预算, 可用现金的95%)
            # 当选不足默认预算时，允许用全部现金买入
            budget = min(DEFAULT_BUY_BUDGET, cash * 0.95)
            if budget < cur_price * LOT_SIZE:
                # 现金额买不起默认数量，尝试用全部现金买
                max_qty = int(cash * 0.95 / cur_price / LOT_SIZE) * LOT_SIZE
                if max_qty <= 0:
                    logger.info(f'⚠️ [{code}] {level} 现金不足: ¥{cash:.0f} 不够买100股@¥{cur_price:.2f}')
                    return 'NO_ACTION'
                else:
                    logger.info(f'⚠️ [{code}] {level} 现金不足默认预算，改用全部现金买 {max_qty}股')
                    budget = cash * 0.95

            # ── 赚钱闸：单票仓位上限裁剪（config.max_position_pct，此前未执行）──
            budget, cap_reason = _cap_budget_by_position_pct(
                conn, _ACCOUNT_ID, code, cur_price, budget
            )
            if budget < cur_price * LOT_SIZE:
                logger.info(f'🚫 [{code}] {cap_reason}')
                _write_review_decision(_ACCOUNT_ID, code, 'max_position_pct_blocked', 0, cap_reason)
                return 'NO_ACTION'
            logger.info(f'✅ [{code}] {cap_reason}')
        finally:
            conn.close()

        # ── REQ-033 日内买入资金预算 + 连续买入冷静期 ─────────────────────
        conn = sqlite3.connect(_DB_PATH)
        try:
            ok, reason, budget_status = _check_daily_buy_controls(conn, _ACCOUNT_ID, code, budget)
        finally:
            conn.close()
        if not ok:
            logger.info(f'🚫 [{code}] {reason}')
            _write_review_decision(_ACCOUNT_ID, code, 'daily_buy_budget_guard', 0, reason)
            return 'NO_ACTION'
        logger.info(f'✅ [{code}] {reason}')

        # ── REQ-092 买入前估值过滤 ────────────────────────────────────
        val_ok, val_reason, val_data = _check_valuation_filter(code, rule)
        if not val_ok:
            logger.info(f'🚫 [{code}] 估值过滤拒绝: {val_reason}')
            import json as _json_val
            _write_review_decision(
                _ACCOUNT_ID, code, 'valuation_filter_blocked', 0,
                f'{val_reason} | 估值数据: {_json_val.dumps(val_data, ensure_ascii=False)}'
            )
            return 'NO_ACTION'
        logger.info(f'✅ [{code}] 估值过滤通过: {val_reason}')

        # ── REQ-036 行业集中度风控 ──────────────────────────────────
        # 获取总资产用于计算行业占比
        conn = sqlite3.connect(_DB_PATH)
        try:
            acct = conn.execute(
                "SELECT total_value FROM sim_account WHERE id=?", (_ACCOUNT_ID,)
            ).fetchone()
            total_value = float(acct[0]) if acct else _load_max_total()
        finally:
            conn.close()
        ind_ok, ind_reason = _check_industry_concentration(
            sqlite3.connect(_DB_PATH), _ACCOUNT_ID, code, total_value)
        if not ind_ok:
            logger.info(f'🚫 [{code}] 行业集中度拒绝: {ind_reason}')
            _write_review_decision(_ACCOUNT_ID, code, 'industry_concentration_blocked', 0, ind_reason)
            return 'NO_ACTION'
        logger.info(f'✅ [{code}] 行业集中度通过: {ind_reason}')

        _write_review_decision(_ACCOUNT_ID, code, 'buy', 1, f'{level} 信号通过风控；{reason}')
        return 'BUY'

    elif level in ('stop_loss', 'soft_stop', 'hard_stop', 'deep_drop'):
        # TASK-20260702-2004-004: 买入后保护期检查
        conn = sqlite3.connect(_DB_PATH)
        try:
            is_protected, protect_reason = _is_protected_by_post_buy(
                conn, code, level, cur_price, _ACCOUNT_ID)
        finally:
            conn.close()
        if is_protected:
            logger.info(f'🛡️ [{code}] {protect_reason}')
            _write_review_decision(_ACCOUNT_ID, code, 'post_buy_protection', 0, protect_reason)
            return 'NO_ACTION'

        # REQ-048 修复：传递 position 参数给 _check_stop_loss_severity()
        severity, sev_action, sev_reason = _check_stop_loss_severity(code, rule, cur_price, position)
        logger.info(f'[{code}] 止损决策: severity={severity}, action={sev_action}')
        return sev_action  # NO_ACTION / SELL_HALF / SELL_ALL / DEFER

    elif level in ('trend_break', 'trend_break_warn'):
        # TASK-20260702-2004-004: 买入后保护期检查
        conn = sqlite3.connect(_DB_PATH)
        try:
            is_protected, protect_reason = _is_protected_by_post_buy(
                conn, code, level, cur_price, _ACCOUNT_ID)
        finally:
            conn.close()
        if is_protected:
            logger.info(f'🛡️ [{code}] {protect_reason}')
            _write_review_decision(_ACCOUNT_ID, code, 'post_buy_protection', 0, protect_reason)
            return 'NO_ACTION'

        # REQ-048 修复：trend_break 之前在 decide_action 中无匹配分支，
        # 导致 threshold_strategy._try_sell('trend_break') 走到末尾 return 'NO_ACTION'，
        # 卖出信号被吞掉——threshold_state 标记 executed 但 sim_positions 仓位仍在。
        # 修复：趋势破位 → SELL_ALL（全仓卖出，趋势破位不应留半仓）
        # 同时也检查仓位是否真的存在（观察股无仓位时返回 NO_ACTION）
        if position and position.get('quantity', 0) > 0:
            # position 参数已传入，直接使用
            logger.info(f'🔴 [{code}] trend_break 触发，全仓卖出（position 参数传入: {position["quantity"]}股）')
            return 'SELL_ALL'
        # 否则查数据库确认
        try:
            conn = sqlite3.connect(_DB_PATH)
            try:
                has_pos = conn.execute(
                    "SELECT quantity FROM sim_positions WHERE account_id=? AND stock_code=? AND quantity > 0",
                    (_ACCOUNT_ID, code)
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            logger.warning(f'[{code}] trend_break 查仓失败({e})，有 position 参数则卖')
            has_pos = None
            if position and position.get('quantity', 0) > 0:
                return 'SELL_ALL'
        if not has_pos:
            logger.info(f'ℹ️ [{code}] trend_break 触发但无持仓，仅提醒')
            return 'NO_ACTION'
        logger.info(f'🔴 [{code}] trend_break 触发，全仓卖出')
        return 'SELL_ALL'

    elif level == 'take_profit':
        # half: first hit sells half; second hit (already scaled) clears runner.
        # full: legacy REQ-066 clear-all behaviour.
        if TAKE_PROFIT_MODE == 'full':
            return 'SELL_ALL'
        try:
            conn = sqlite3.connect(_DB_PATH)
            try:
                already = _has_sell_since_last_buy(conn, code, _ACCOUNT_ID)
                row = conn.execute(
                    "SELECT quantity FROM sim_positions WHERE account_id=? AND stock_code=? AND quantity > 0",
                    (_ACCOUNT_ID, code),
                ).fetchone()
            finally:
                conn.close()
        except Exception:
            already, row = False, None
        qty = int(row[0]) if row else 0
        if already:
            logger.info(f'🟡 [{code}] take_profit 二次触发（已半仓过），余仓清仓')
            return 'SELL_ALL'
        half_qty = int(qty / 2 / LOT_SIZE) * LOT_SIZE if qty else 0
        if half_qty < LOT_SIZE:
            # Single lot cannot scale — bank full at take_profit trigger.
            logger.info(f'🟡 [{code}] take_profit 但仓位不足半仓（qty={qty}），全仓止盈')
            return 'SELL_ALL'
        logger.info(f'🟡 [{code}] take_profit 半仓止盈，余仓 ATR 跟踪')
        return 'SELL_HALF'
    elif level in ('take_profit_half', 'half_out', 'scale_out'):
        # REQ-048: 半仓止盈 / 回到成本线减仓 / +1R 成本半仓
        return 'SELL_HALF'

    elif level == 'trend_break_buy':
        # 趋势突破买入：价格突破阻力位 + 放量 → 买入
        # 与 buy_zone/buy_strong 共享相同的风控检查
        logger.info(f'📈 [{code}] trend_break_buy 触发，执行买入流程')
        # 直接复用 buy_zone/buy_strong 的买入逻辑
        # 持仓数量硬上限检查
        conn = sqlite3.connect(_DB_PATH)
        try:
            total_pos = conn.execute(
                "SELECT COUNT(*) FROM sim_positions WHERE account_id=? AND quantity > 0",
                (_ACCOUNT_ID,)
            ).fetchone()[0]
        finally:
            conn.close()
        if total_pos >= MAX_TOTAL_POSITIONS:
            reason = f'总持仓数({total_pos})≥上限({MAX_TOTAL_POSITIONS})，拒绝新建 {code}'
            logger.info(f'🚫 [{code}] {reason}')
            _write_review_decision(_ACCOUNT_ID, code, 'position_count_limit', 0, reason)
            return 'NO_ACTION'

        # 检查价格合理性
        ok, reason = check_price_sanity(code, cur_price, 'BUY')
        if not ok:
            logger.info(f'⚠️ [{code}] trend_break_buy 价格检查失败: {reason}')
            return 'NO_ACTION'

        # 检查账户现金
        conn = sqlite3.connect(_DB_PATH)
        try:
            acct = conn.execute(
                "SELECT cash, total_value FROM sim_account WHERE id=?", (_ACCOUNT_ID,)
            ).fetchone()
            if not acct:
                return 'NO_ACTION'
            cash = float(acct[0])
            budget = min(DEFAULT_BUY_BUDGET, cash * 0.95)
            if budget < cur_price * LOT_SIZE:
                max_qty = int(cash * 0.95 / cur_price / LOT_SIZE) * LOT_SIZE
                if max_qty <= 0:
                    logger.info(f'⚠️ [{code}] trend_break_buy 现金不足: ¥{cash:.0f} 不够买100股@¥{cur_price:.2f}')
                    return 'NO_ACTION'
                budget = cash * 0.95
        finally:
            conn.close()

        # 日内买入资金预算检查
        conn = sqlite3.connect(_DB_PATH)
        try:
            ok, reason, budget_status = _check_daily_buy_controls(conn, _ACCOUNT_ID, code, budget)
        finally:
            conn.close()
        if not ok:
            logger.info(f'🚫 [{code}] {reason}')
            _write_review_decision(_ACCOUNT_ID, code, 'daily_buy_budget_guard', 0, reason)
            return 'NO_ACTION'

        # ── REQ-092 买入前估值过滤 ────────────────────────────────────
        val_ok, val_reason, val_data = _check_valuation_filter(code, rule)
        if not val_ok:
            logger.info(f'🚫 [{code}] 估值过滤拒绝: {val_reason}')
            import json as _json_val
            _write_review_decision(
                _ACCOUNT_ID, code, 'valuation_filter_blocked', 0,
                f'{val_reason} | 估值数据: {_json_val.dumps(val_data, ensure_ascii=False)}'
            )
            return 'NO_ACTION'
        logger.info(f'✅ [{code}] 估值过滤通过: {val_reason}')

        _write_review_decision(_ACCOUNT_ID, code, 'trend_break_buy', 1, f'趋势突破信号通过风控；{reason}')
        return 'BUY'

    return 'NO_ACTION'


def execute_trade(rule: dict, cur_price: float) -> dict:
    warnings.warn(
        "execute_trade is deprecated, use quant_core.execution.ExecutionPolicy.execute() instead",
        DeprecationWarning, stacklevel=2,
    )
    """持仓股止损止盈。
    
    返回: {'updated': bool, 'highest': float, 'trailing': float, 'reason': str}
    """
    code = rule["code"]
    name = rule["name"]
    cur_price = quantize_price(cur_price)

    # REQ-046: 先读仓位信息，传给 decide_action 获取正确决策
    position = None
    stop_levels = {'stop_loss', 'soft_stop', 'hard_stop', 'deep_drop'}
    if rule.get('level') in stop_levels:
        try:
            conn_pos = sqlite3.connect(_DB_PATH)
            _ensure_trailing_columns(conn_pos)
            row_pos = conn_pos.execute(
                "SELECT quantity, avg_cost, highest_price, trailing_stop_price "
                "FROM sim_positions WHERE account_id=? AND stock_code=?",
                (_ACCOUNT_ID, code)
            ).fetchone()
            conn_pos.close()
            if row_pos and row_pos[0] > 0:
                position = {
                    'quantity': row_pos[0],
                    'avg_cost': row_pos[1],
                    'highest_price': row_pos[2],
                    'trailing_stop_price': row_pos[3],
                }
        except Exception as e:
            logger.warning(f"读取仓位信息失败 {code}: {e}")

    action = decide_action(rule, cur_price, position=position)
    severity = None
    severity_label = ''

    # Cost-based +1R half take-profit even when current rule is not take_profit.
    if action in ('NO_ACTION', 'DEFER', None):
        try:
            conn_so = sqlite3.connect(_DB_PATH)
            try:
                row_so = conn_so.execute(
                    "SELECT quantity, avg_cost FROM sim_positions "
                    "WHERE account_id=? AND stock_code=? AND quantity > 0",
                    (_ACCOUNT_ID, code),
                ).fetchone()
                if row_so:
                    ok_so, reason_so = _check_cost_scale_out(
                        conn_so, code, cur_price, int(row_so[0]), float(row_so[1]), _ACCOUNT_ID,
                    )
                    if ok_so:
                        action = 'SELL_HALF'
                        rule = dict(rule)
                        rule['level'] = 'scale_out'
                        rule['message'] = reason_so
                        logger.info(f'🟡 [{code}] {reason_so}')
                        try:
                            _write_review_decision(_ACCOUNT_ID, code, 'scale_out', 1, reason_so)
                        except Exception:
                            pass
            finally:
                conn_so.close()
        except Exception as e:
            logger.warning(f'[{code}] scale_out 检查失败: {e}')
    
    # 🔥 P0+P2: 智能止损三档评级 + 跟踪止损 — 只对 stop_loss 类 level 作修正
    stop_levels = {'stop_loss', 'soft_stop', 'hard_stop', 'deep_drop'}
    severity_msg = ''
    if rule.get('level') in stop_levels:
        # P2: 先拉仓位，拿 trailing_stop_price
        position = None
        try:
            conn = sqlite3.connect(_DB_PATH)
            _ensure_trailing_columns(conn)
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
                _ensure_trailing_columns(conn)
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
        
        # TASK-20260702-2004-004: severity check 前再做一次保护期检查
        # （decide_action 已检查，但这里的 severity 可能覆盖 action 为 SELL）
        conn = sqlite3.connect(_DB_PATH)
        try:
            is_protected, protect_reason = _is_protected_by_post_buy(
                conn, code, rule.get('level', ''), cur_price, _ACCOUNT_ID)
        finally:
            conn.close()
        if is_protected:
            logger.info(f'🛡️ [{code}] {protect_reason}（severity check 前）')
            try:
                _write_review_decision(_ACCOUNT_ID, code, 'post_buy_protection', 0, protect_reason)
            except Exception:
                pass
            return {'action': 'NO_ACTION', 'success': True,
                    'message': f'买入后保护期内抑制止损: {protect_reason}',
                    'trade': None, 'severity': severity, 'severity_label': severity_label}

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
        # REQ-046/099: 近收盘软止损升级为 SELL_ALL（不拖到明天；避免半仓残留）
        if _is_late_session():
            logger.info(f"🔥 [{code}] 软止损近收盘升级为 SELL_ALL: {severity_msg}")
            action = 'SELL_ALL'
        else:
            return {'action': action, 'success': True, 'message': f'软止损预警（不自动卖): {severity_msg}',
                    'trade': None, 'severity': severity, 'severity_label': severity_label}

    if action == 'BUY':
        # REQ-049 修复：动态计算预算，与 decide_action 一致
        conn2 = sqlite3.connect(_DB_PATH)
        try:
            acct2 = conn2.execute(
                "SELECT cash, total_value FROM sim_account WHERE id=?", (_ACCOUNT_ID,)
            ).fetchone()
            if not acct2:
                return {'action': action, 'success': False, 'message': '账户不存在'}
            cash2 = float(acct2[0])
            budget = min(DEFAULT_BUY_BUDGET, cash2 * 0.95)
            if budget < cur_price * LOT_SIZE:
                # 现金不够默认预算，改用全部现金
                budget = cash2 * 0.95
            # 赚钱闸：执行侧再次裁剪单票仓位（防 decide 与 execute 竞态）
            budget, cap_reason = _cap_budget_by_position_pct(
                conn2, _ACCOUNT_ID, code, cur_price, budget
            )
            if budget < cur_price * LOT_SIZE:
                return {
                    'action': 'NO_ACTION', 'success': True,
                    'message': cap_reason, 'trade': None,
                }
        finally:
            conn2.close()
        qty = int(budget / cur_price / LOT_SIZE) * LOT_SIZE
        if qty <= 0:
            return {'action': action, 'success': False, 'message': f'计算买入数量失败: budget={budget}, price={cur_price}'}

        conn = sqlite3.connect(_DB_PATH)
        try:
            conn.execute("BEGIN")
            _ensure_trailing_columns(conn)
            acct = conn.execute(
                "SELECT cash, total_value FROM sim_account WHERE id=?", (_ACCOUNT_ID,)
            ).fetchone()
            if not acct or float(acct[0]) < cur_price * qty:
                conn.execute("ROLLBACK")
                return {'action': action, 'success': False, 'message': f'现金不足: ¥{acct[0] if acct else 0:.0f}'}

            if _has_today_buy(conn, code):
                msg = f'今日已买入过 {code}，跳过重复买入信号'
                conn.execute("ROLLBACK")
                logger.info(f"🚫 [{code}] {msg}")
                try:
                    _write_review_decision(_ACCOUNT_ID, code, 'duplicate_buy_guard', 0, msg)
                except Exception as e:
                    logger.warning(f"写入重复买入风控记录失败 {code}: {e}")
                return {'action': 'NO_ACTION', 'success': True, 'message': msg, 'trade': None,
                        'severity': severity, 'severity_label': severity_label}

            # BUG-011: 同日反向交易防御 — 今日已卖出则禁止再买入
            if _has_today_sell(conn, code):
                msg = f'BUG-011: 今日已有 {code} 卖出成交，同日反向交易规则禁止再买入'
                conn.execute("ROLLBACK")
                logger.info(f"🚫 [{code}] {msg}")
                try:
                    _write_review_decision(_ACCOUNT_ID, code, 'same_day_reverse_guard', 0, msg)
                except Exception as e:
                    logger.warning(f"写入同日反向风控记录失败 {code}: {e}")
                return {'action': 'NO_ACTION', 'success': True, 'message': msg, 'trade': None,
                        'severity': severity, 'severity_label': severity_label}

            # TASK-20260705-0215-004: 近期止损冷却期 — 若近5个日历日内有买+卖成对，禁止再买入
            if _has_recent_stop_loss(conn, code, lookback_days=5):
                msg = f'TASK-0215-004: {code} 近5个日历日内有买+卖成对（信号质量差），冷却期满前禁止买入'
                conn.execute("ROLLBACK")
                logger.info(f"🛡️ [{code}] {msg}")
                try:
                    _write_review_decision(_ACCOUNT_ID, code, 'stop_loss_cooldown_guard', 0, msg)
                except Exception as e:
                    logger.warning(f"写入止损冷却期风控记录失败 {code}: {e}")
                return {'action': 'NO_ACTION', 'success': True, 'message': msg, 'trade': None,
                        'severity': severity, 'severity_label': severity_label}

            commission = quantize_amount(cur_price * qty * COMMISSION_RATE)
            amount = quantize_amount(cur_price * qty + commission)

            # REQ-033: 成交前在同一事务中再次校验日内预算/冷静期，避免并发或重算预算穿透。
            ok, reason, _budget_status = _check_daily_buy_controls(conn, _ACCOUNT_ID, code, amount)
            if not ok:
                conn.execute("ROLLBACK")
                logger.info(f"🚫 [{code}] {reason}")
                try:
                    _write_review_decision(_ACCOUNT_ID, code, 'daily_buy_budget_guard', 0, reason)
                except Exception as e:
                    logger.warning(f"写入日内预算风控记录失败 {code}: {e}")
                return {'action': 'NO_ACTION', 'success': True, 'message': reason, 'trade': None,
                        'severity': severity, 'severity_label': severity_label}

            # REQ-069: 只扣现金；总资产稍后按 cash+Σmv 重算（勿把 total_value 当现金扣）
            conn.execute(
                "UPDATE sim_account SET cash=cash-? WHERE id=?",
                (amount, _ACCOUNT_ID)
            )
            # 更新或插入仓位
            existing = conn.execute(
                "SELECT quantity, avg_cost FROM sim_positions WHERE account_id=? AND stock_code=?",
                (_ACCOUNT_ID, code)
            ).fetchone()
            if existing:
                new_qty = existing[0] + qty
                new_cost = quantize_cost((existing[0] * existing[1] + qty * cur_price) / new_qty)
                conn.execute(
                    "UPDATE sim_positions SET quantity=?, avg_cost=?, current_price=?, market_value=?, pnl=?, pnl_pct=?, "
                    "highest_price=MAX(COALESCE(highest_price, ?), ?) "
                    "WHERE account_id=? AND stock_code=?",
                    (new_qty, new_cost, cur_price, quantize_amount(new_qty * cur_price),
                     quantize_amount((cur_price - new_cost) * new_qty), (cur_price - new_cost) / new_cost * 100,
                     cur_price, cur_price, _ACCOUNT_ID, code)
                )
            else:
                # REQ-059 修复：新建仓位时初始化 trailing_stop_price = cur_price * 0.92（默认-8%止损）
                _init_trailing_stop = round(cur_price * 0.92, 2)
                conn.execute(
                    "INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct, highest_price, trailing_stop_price) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (_ACCOUNT_ID, code, name, qty, cur_price, cur_price, quantize_amount(qty * cur_price),
                     0.0, 0.0, cur_price, _init_trailing_stop)
                )
            _recalc_account_total(conn, _ACCOUNT_ID)
            # 写入成交记录
            trade_date = datetime.now().strftime('%Y-%m-%d')
            trade_time = datetime.now().strftime('%H:%M:%S')
            # REQ-057 / REQ-062 / TASK-20260709: signal_reason 必须以成交价为准。
            # 禁止把规则文案里的「跌至 X / MA10=Y」当成交参考价（串价根因）。
            _sig_level = rule.get('level', '')
            try:
                _trigger_val = float(rule.get('trigger') or 0)
            except (TypeError, ValueError):
                _trigger_val = 0.0
            if _sig_level in ('buy_zone', 'buy_strong'):
                _signal_reason = (
                    f"{_sig_level}|建仓价={cur_price:.2f}"
                    + (f"|触发阈值={_trigger_val:.2f}" if _trigger_val > 0 else "")
                    + f"|{name} {_sig_level} 试探建仓"
                )
            else:
                _raw_msg = (rule.get('message') or '').strip()
                _signal_reason = f"{_sig_level}|{_raw_msg}".strip('|') or _sig_level
            conn.execute(
                "INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, stock_name, direction, price, quantity, amount, commission, signal_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_ACCOUNT_ID, trade_date, trade_time, code, name, 'BUY', cur_price, qty, amount, commission, _signal_reason)
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
            _ensure_trailing_columns(conn)
            row = conn.execute(
                "SELECT quantity, avg_cost FROM sim_positions WHERE account_id=? AND stock_code=?",
                (_ACCOUNT_ID, code)
            ).fetchone()
            if not row or row[0] <= 0:
                conn.execute("ROLLBACK")
                return {'action': action, 'success': False, 'message': f'无持仓可卖 {code}'}

            # TASK-20260702-2004-001: 同日反向交易防御 — 今日刚买入则禁止当日卖出
            # 防止 buy_strong + trend_break 同K线矛盾信号导致瞬时反向交易
            # 例外：硬止损 / 成本浮亏已达 stop_loss_pct（默认 -8%）必须允许出清
            if _has_today_buy(conn, code):
                allowed, allow_reason = _same_day_hard_stop_allowed(
                    conn, code, cur_price, rule.get('level', ''), _ACCOUNT_ID)
                if not allowed:
                    msg = f'TASK-2004-001: 今日刚买入 {code}，拒绝同日卖出（buy_strong+trend_break 矛盾防御）'
                    conn.execute("ROLLBACK")
                    logger.info(f"🛡️ [{code}] {msg}")
                    try:
                        _write_review_decision(_ACCOUNT_ID, code, 'same_day_reverse_guard', 0, msg)
                    except Exception as e:
                        logger.warning(f"写入同日反向风控记录失败 {code}: {e}")
                    return {'action': 'NO_ACTION', 'success': True, 'message': msg, 'trade': None,
                            'severity': severity, 'severity_label': severity_label}
                logger.info(f"⚠️ [{code}] 同日卖出放行: {allow_reason}")
                try:
                    _write_review_decision(_ACCOUNT_ID, code, 'same_day_hard_stop_bypass', 1, allow_reason)
                except Exception:
                    pass

            if action == 'SELL_HALF':
                sell_qty = int(row[0] / 2 / LOT_SIZE) * LOT_SIZE
                # 对齐 take_profit：不足一手半仓 → 清仓（防止损残留 100 股卡死）
                if sell_qty < LOT_SIZE:
                    logger.info(f'⚠️ [{code}] SELL_HALF 不足一手（qty={row[0]}），升级清仓')
                    sell_qty = row[0]
                    action = 'SELL_ALL'
            else:
                sell_qty = row[0]

            if sell_qty <= 0:
                conn.execute("ROLLBACK")
                return {'action': action, 'success': False, 'message': f'计算卖出数量失败'}

            commission = quantize_amount(cur_price * sell_qty * COMMISSION_RATE)
            stamp_tax = quantize_amount(cur_price * sell_qty * STAMP_TAX_RATE)
            amount = quantize_amount(cur_price * sell_qty - commission - stamp_tax)

            # REQ-069: 只加现金；总资产按 cash+Σmv 重算
            conn.execute(
                "UPDATE sim_account SET cash=cash+? WHERE id=?",
                (amount, _ACCOUNT_ID)
            )
            new_qty = row[0] - sell_qty
            if new_qty > 0:
                new_cost = row[1]  # 剩余仓位成本不变
                # After scale-out / half take-profit, ratchet trailing to at least breakeven.
                trail_bump = None
                if action == 'SELL_HALF' and str(rule.get('level', '')) in (
                    'take_profit', 'take_profit_half', 'half_out', 'scale_out',
                ):
                    trail_bump = round(float(new_cost), 2)
                if trail_bump is not None:
                    conn.execute(
                        "UPDATE sim_positions SET quantity=?, current_price=?, market_value=?, pnl=?, pnl_pct=?, "
                        "trailing_stop_price=MAX(COALESCE(trailing_stop_price, 0), ?) "
                        "WHERE account_id=? AND stock_code=?",
                        (new_qty, cur_price, quantize_amount(new_qty * cur_price),
                         quantize_amount((cur_price - new_cost) * new_qty),
                         (cur_price - new_cost) / new_cost * 100 if new_cost else 0,
                         trail_bump, _ACCOUNT_ID, code)
                    )
                else:
                    conn.execute(
                        "UPDATE sim_positions SET quantity=?, current_price=?, market_value=?, pnl=?, pnl_pct=? "
                        "WHERE account_id=? AND stock_code=?",
                        (new_qty, cur_price, quantize_amount(new_qty * cur_price),
                         quantize_amount((cur_price - new_cost) * new_qty),
                         (cur_price - new_cost) / new_cost * 100 if new_cost else 0,
                         _ACCOUNT_ID, code)
                    )
            else:
                conn.execute(
                    "DELETE FROM sim_positions WHERE account_id=? AND stock_code=?",
                    (_ACCOUNT_ID, code)
                )
            _recalc_account_total(conn, _ACCOUNT_ID)
            # 写入成交记录
            trade_date = datetime.now().strftime('%Y-%m-%d')
            trade_time = datetime.now().strftime('%H:%M:%S')
            # REQ-057: 回写 signal_reason，避免 SELL 成交记录 signal_reason 为空无法追源
            _signal_reason = f"{rule.get('level', '')}|{rule.get('message', '')}".strip('|')
            conn.execute(
                "INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, stock_name, direction, price, quantity, amount, commission, signal_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_ACCOUNT_ID, trade_date, trade_time, code, name, 'SELL', cur_price, sell_qty, amount, commission, _signal_reason)
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
