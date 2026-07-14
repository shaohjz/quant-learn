"""
vqlearn/services/threshold_state.py — 阈值触发状态机

为卖出规则（trend_break / take_profit）实现「两段确认」：
- 第一段：盘中价格触发 → pending 状态（不下单）
- 第二段：当日 14:55 后收盘价确认 ≤ 阈值 → armed 状态
- 第三段：次日 09:30-09:35 平均价仍 ≤ 阈值 → confirmed 状态，触发卖单

为买入规则（buy_zone / buy_strong）保持「当下立即触发」。

跨进程跨日持久化到 sqlite。
"""
from __future__ import annotations

import os
import sys
import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# 强制使用 live_mirror DB
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))

from sim.db import get_conn

# 卖出规则需要两段确认；买入规则当下触发
SELL_RULES = {'trend_break', 'take_profit', 'take_profit_half'}
BUY_RULES = {'buy_zone', 'buy_strong'}


def _today() -> str:
    return date.today().isoformat()


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _is_after_close_confirm_window() -> bool:
    """当前是否在收盘价确认窗口（14:55 之后到 15:30）"""
    now = datetime.now().time()
    return time(14, 55) <= now <= time(15, 30)


def _is_in_next_day_confirm_window() -> bool:
    """当前是否在次日开盘确认窗口（9:35-9:40，等开盘 5 分钟均价稳定）"""
    now = datetime.now().time()
    return time(9, 35) <= now <= time(9, 40)


# ============================================================
#  买入规则：直接判定（无两段确认）
# ============================================================
def _has_sell_today(stock_code: str) -> bool:
    """BUG-011: 检查今日是否已有该股票的 SELL 成交。

    用于同日反向交易防御：若今日已卖出，则不应允许再买入。
    """
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM sim_trades "
            "WHERE account_id=1 AND stock_code=? AND trade_date=? "
            "AND direction='SELL' LIMIT 1",
            (stock_code, _today()),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def should_buy_now(stock_code: str, rule_name: str) -> tuple[bool, str]:
    """
    买入规则的去重判定。
    今日同一规则只能触发一次（buy 不需要次日确认，但需要当日去重）。
    BUG-011: 额外检查今日是否有 SELL 成交，防止同日反向交易（自成交）。
    Returns: (允许买入, 原因)
    """
    if rule_name not in BUY_RULES:
        return False, f"非买入规则: {rule_name}"

    # BUG-011: 同日反向交易防御 — 今日已卖出则禁止再买入
    if _has_sell_today(stock_code):
        return False, "BUG-011: 今日已有卖出成交，同日反向交易规则禁止再买入"

    conn = get_conn()
    row = conn.execute(
        """SELECT id, status FROM threshold_state
           WHERE stock_code=? AND rule_name=? AND first_hit_date=?""",
        (stock_code, rule_name, _today())
    ).fetchone()
    conn.close()

    if row is None:
        return True, "新触发"
    if row['status'] == 'executed':
        return False, "今日已执行过"
    return True, f"重试触发（status={row['status']}）"


def record_buy_executed(stock_code: str, stock_name: str, rule_name: str,
                        threshold: float, fill_price: float, notes: str = ""):
    """记录买入已执行"""
    conn = get_conn()
    conn.execute(
        """INSERT INTO threshold_state
           (stock_code, stock_name, rule_name, rule_threshold,
            first_hit_date, first_hit_price, first_hit_time,
            status, fired_today, last_check_date, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'executed', 1, ?, ?)
           ON CONFLICT(stock_code, rule_name, first_hit_date) DO UPDATE SET
            status='executed',
            fired_today=1,
            updated_at=CURRENT_TIMESTAMP,
            notes=excluded.notes
        """,
        (stock_code, stock_name, rule_name, threshold,
         _today(), fill_price, _now(), _today(), notes)
    )
    conn.close()


# ============================================================
#  卖出规则：两段确认
# ============================================================
def evaluate_sell_signal(stock_code: str, stock_name: str, rule_name: str,
                        threshold: float, current_price: float,
                        is_close_price: bool = False) -> tuple[str, str]:
    """
    判定卖出信号当前所处阶段，并推进状态机。

    Args:
        is_close_price: 当前价格是否是收盘价（14:55 后由外部判定传入）

    Returns:
        (action, reason)
        action: 'wait' | 'execute' | 'reset'
            wait    = 仅记录/推进状态，不下单
            execute = 真下卖单
            reset   = 阈值已不再生效，状态记录可清理
        reason: 描述
    """
    if rule_name not in SELL_RULES:
        return 'wait', f"非卖出规则: {rule_name}"

    today = _today()
    is_breaking = (
        (rule_name in ('trend_break',) and current_price <= threshold) or
        (rule_name in ('take_profit', 'take_profit_half') and current_price >= threshold)
    )

    conn = get_conn()
    # 找该股票该规则的最新一条记录
    row = conn.execute(
        """SELECT * FROM threshold_state
           WHERE stock_code=? AND rule_name=?
           ORDER BY first_hit_date DESC LIMIT 1""",
        (stock_code, rule_name)
    ).fetchone()

    if row is None:
        # 没有任何记录，且当前未破阈值
        if not is_breaking:
            conn.close()
            return 'wait', "未触发"
        # 第一次盘中触发
        conn.execute(
            """INSERT INTO threshold_state
               (stock_code, stock_name, rule_name, rule_threshold,
                first_hit_date, first_hit_price, first_hit_time,
                status, fired_today, last_check_date, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, '盘中首次触发')""",
            (stock_code, stock_name, rule_name, threshold,
             today, current_price, _now(), today)
        )
        conn.close()
        return 'wait', f"⏱️ 盘中首次触发 {current_price:.2f} vs {threshold:.2f}（pending，等收盘确认）"

    # 已有记录，按 status 推进
    status = row['status']
    first_hit_date = row['first_hit_date']

    if status == 'executed':
        conn.close()
        return 'wait', "今日已执行过卖单"

    if status == 'expired':
        # 阈值之前曾失效。如果今天又破了，重新进入 pending
        if is_breaking and first_hit_date != today:
            conn.execute(
                """INSERT INTO threshold_state
                   (stock_code, stock_name, rule_name, rule_threshold,
                    first_hit_date, first_hit_price, first_hit_time,
                    status, fired_today, last_check_date, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, '阈值再次触发')""",
                (stock_code, stock_name, rule_name, threshold,
                 today, current_price, _now(), today)
            )
            conn.close()
            return 'wait', f"⏱️ 阈值再次触发 {current_price:.2f}（pending）"
        conn.close()
        return 'wait', "已失效"

    if status == 'pending':
        # 当前在 pending，看今天是不是 first_hit_date
        if first_hit_date == today:
            # 是今天的 pending；等到 14:55 后用收盘价升级 armed
            if is_close_price and is_breaking:
                conn.execute(
                    """UPDATE threshold_state SET
                        status='armed',
                        close_confirmed_at=?,
                        close_price=?,
                        last_check_date=?,
                        notes='收盘价仍破阈值，升级armed',
                        updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (today, current_price, today, row['id'])
                )
                conn.close()
                return 'wait', f"✅ 收盘确认 {current_price:.2f} ≤ {threshold:.2f}（armed，明日开盘再确认）"
            elif is_close_price and not is_breaking:
                # 盘中触发但收盘已回升 → 假摔，作废
                conn.execute(
                    "UPDATE threshold_state SET status='expired', notes='收盘价已回升，假摔', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (row['id'],)
                )
                conn.close()
                return 'reset', f"假摔回升 {current_price:.2f}，作废"
            else:
                conn.close()
                return 'wait', f"今日 pending 中（first_hit_date={first_hit_date}）"
        else:
            # pending 跨日没确认就过期，重置状态
            conn.execute(
                "UPDATE threshold_state SET status='expired', notes='pending跨日未确认', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row['id'],)
            )
            # 看今天是否再次破
            if is_breaking:
                conn.execute(
                    """INSERT INTO threshold_state
                       (stock_code, stock_name, rule_name, rule_threshold,
                        first_hit_date, first_hit_price, first_hit_time,
                        status, fired_today, last_check_date, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, '前日pending过期，今日重新触发')""",
                    (stock_code, stock_name, rule_name, threshold,
                     today, current_price, _now(), today)
                )
                conn.close()
                return 'wait', f"前日 pending 过期，今日重新触发 {current_price:.2f}"
            conn.close()
            return 'reset', "前日 pending 过期"

    if status == 'armed':
        # 已 armed，等次日 9:35-9:40 用开盘 5min 价确认
        if first_hit_date == today:
            # 同日不可能 armed（armed 是 14:55 后才上的），保险
            conn.close()
            return 'wait', "armed（今日内不再处理）"

        if _is_in_next_day_confirm_window() and is_breaking:
            # 次日开盘确认通过 → execute
            conn.execute(
                """UPDATE threshold_state SET
                    status='confirmed',
                    next_day_confirmed_at=?,
                    next_day_price=?,
                    last_check_date=?,
                    notes='次日开盘5min确认，触发卖单',
                    updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (today, current_price, today, row['id'])
            )
            conn.close()
            return 'execute', f"🚀 次日开盘确认 {current_price:.2f} ≤ {threshold:.2f}，执行卖单"

        if _is_in_next_day_confirm_window() and not is_breaking:
            # 次日开盘已回升 → 作废
            conn.execute(
                "UPDATE threshold_state SET status='expired', notes='次日开盘回升，作废', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row['id'],)
            )
            conn.close()
            return 'reset', f"次日开盘回升 {current_price:.2f}，作废"

        # 不在确认窗口内
        conn.close()
        return 'wait', f"armed（等明日 9:35-9:40 确认）"

    if status == 'confirmed':
        # 已确认但未 execute（一般紧接着会被 mark executed）
        conn.close()
        return 'execute', "confirmed 状态待执行"

    conn.close()
    return 'wait', f"未知 status: {status}"


def record_sell_executed(stock_code: str, rule_name: str, fill_price: float, notes: str = "") -> int:
    """记录卖出已执行。返回实际更新行数（REQ-048：0 行 = 状态未匹配，勿当成功闭环）。"""
    conn = get_conn()
    today = _today()
    cur = conn.execute(
        """UPDATE threshold_state SET
            status='executed',
            notes=?,
            updated_at=CURRENT_TIMESTAMP
           WHERE stock_code=? AND rule_name=? AND status IN ('confirmed','armed')
             AND first_hit_date <= ?""",
        (notes or f'卖单成交 {fill_price:.2f}', stock_code, rule_name, today)
    )
    updated = int(cur.rowcount or 0)
    conn.close()
    return updated


def reset_stuck_confirmed(stock_code: str, rule_name: str, notes: str = "") -> int:
    """REQ-048: 卖出失败或状态悬挂时，将 confirmed/armed 置为 expired，避免永远卡住。"""
    conn = get_conn()
    cur = conn.execute(
        """UPDATE threshold_state SET
            status='expired',
            notes=?,
            updated_at=CURRENT_TIMESTAMP
           WHERE stock_code=? AND rule_name=?
             AND status IN ('confirmed', 'armed')""",
        (notes or '重置卡住的 confirmed/armed', stock_code, rule_name),
    )
    updated = int(cur.rowcount or 0)
    conn.close()
    if updated:
        logger.warning(
            "reset_stuck_confirmed %s/%s -> expired (%d rows): %s",
            stock_code, rule_name, updated, notes,
        )
    return updated


def audit_executed_without_trade(account_id: int = 1) -> list[dict]:
    """REQ-048: 找出 threshold_state.executed 但 sim_positions 仍有仓位的脏记录。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT t.stock_code, t.rule_name, t.status, t.notes, t.updated_at,
                   p.quantity, p.avg_cost
              FROM threshold_state t
              JOIN sim_positions p
                ON p.stock_code = t.stock_code
               AND p.account_id = ?
               AND p.quantity > 0
             WHERE t.status = 'executed'
               AND t.rule_name IN ('trend_break', 'take_profit', 'take_profit_half',
                                   'stop_loss', 'soft_stop', 'hard_stop', 'deep_drop')
             ORDER BY t.updated_at DESC
            """,
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("audit_executed_without_trade failed: %s", e)
        return []
    finally:
        conn.close()


def cleanup_orphaned_executed(account_id: int = 1, dry_run: bool = True) -> list[dict]:
    """REQ-048: 清理「executed 但仍有仓」的卖出状态 —— 重置为 expired 以便重试真卖。

    买入规则不碰（executed + 有仓是正常）。
    """
    orphans = audit_executed_without_trade(account_id=account_id)
    if dry_run or not orphans:
        return orphans
    conn = get_conn()
    try:
        for row in orphans:
            conn.execute(
                """UPDATE threshold_state SET
                    status='expired',
                    notes=?,
                    updated_at=CURRENT_TIMESTAMP
                   WHERE stock_code=? AND rule_name=? AND status='executed'""",
                (
                    f"REQ-048 cleanup: executed但仓位仍在 qty={row.get('quantity')}",
                    row["stock_code"],
                    row["rule_name"],
                ),
            )
    finally:
        conn.close()
    return orphans


def mark_close_confirm_for_all_pending(get_close_price_fn):
    """
    收盘后批量推进所有 pending → armed/expired。
    在 14:55 后由外部 cron 调用一次。

    get_close_price_fn(stock_code) -> float
    """
    conn = get_conn()
    today = _today()
    pendings = conn.execute(
        """SELECT * FROM threshold_state WHERE status='pending' AND first_hit_date=?""",
        (today,)
    ).fetchall()

    upgraded, expired = [], []
    for row in pendings:
        try:
            close_price = get_close_price_fn(row['stock_code'])
            if close_price is None:
                continue
            threshold = row['rule_threshold']
            rule = row['rule_name']
            is_breaking = (
                (rule == 'trend_break' and close_price <= threshold) or
                (rule in ('take_profit', 'take_profit_half') and close_price >= threshold)
            )
            if is_breaking:
                conn.execute(
                    """UPDATE threshold_state SET status='armed', close_confirmed_at=?,
                       close_price=?, notes='收盘价确认，armed', updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (today, close_price, row['id'])
                )
                upgraded.append((row['stock_code'], rule, close_price))
            else:
                conn.execute(
                    """UPDATE threshold_state SET status='expired',
                       close_price=?, notes='盘中破但收盘回升，假摔', updated_at=CURRENT_TIMESTAMP
                       WHERE id=?""",
                    (close_price, row['id'])
                )
                expired.append((row['stock_code'], rule, close_price))
        except Exception as e:
            logger.exception(f"close confirm failed for {row['stock_code']}: {e}")

    conn.close()
    return upgraded, expired


def list_armed_for_today_check():
    """返回今天需要次日开盘确认的所有 armed 记录"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM threshold_state WHERE status='armed'"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
