"""REQ-058: SELL 成交与 threshold_state 信号的对账与溯源。

背景
----
2026-06-02 当日 2 笔 SELL(600330/002453) 的 signal_reason 为 NULL，无法追溯
触发规则（止损/止盈/trend_break）。同时成交与 threshold_state 的 armed/confirmed
记录无法对账，信号-成交链路断裂。

本模块提供：
  1) ``build_sell_signal_reason``  —— 统一生成「规则名+触发价+量能」的 signal_reason，
     供所有 SELL 写入路径回填，避免再次出现 NULL。
  2) ``reconcile_sell_signals``    —— 对账当日某账户的 SELL 成交与 threshold_state
     的卖出信号记录，输出缺口（orphan_sells / unmatched_signals）。
  3) ``audit_all_accounts``        —— 同时对 account_id=1(sim) 与 account_id=2(real)
     做对账，区分两条信号-成交链路。

设计原则：纯函数 + 显式传入 db_path，便于测试；不依赖 sim/db.py 的全局常量。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# threshold_state 中属于「卖出」语义的规则名
SELL_RULES = ("trend_break", "take_profit", "take_profit_half", "stop_loss", "trailing_stop")

# threshold_state 中可视为「已触发/待执行」的卖出状态（用于和成交对账）
ARMED_STATUSES = ("armed", "confirmed", "executed")

# 清仓后仍可能悬挂、需级联失效的活跃状态（不含 executed）
ACTIVE_ORPHAN_STATUSES = ("pending", "armed", "confirmed")

ACCOUNT_LABELS = {1: "sim", 2: "real", 3: "swing"}


def normalize_stock_code(stock_code: str) -> str:
    """统一为 6 位数字代码（去掉交易所前缀）。"""
    raw = str(stock_code or "").strip().upper()
    for prefix in ("SH", "SZ", "BJ"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else ""


def expire_thresholds_on_flat(
    cur: sqlite3.Cursor,
    stock_code: str,
    *,
    note: str = "清仓后自动失效",
    final_status: str = "expired",
) -> int:
    """持仓清仓后级联失效同标的卖出 threshold_state（REQ-058）。

    返回受影响行数。无 threshold_state 表时静默返回 0。
    final_status 通常为 expired；止损自动成交路径可用 executed。
    """
    if not _table_exists(cur, "threshold_state"):
        return 0
    code = normalize_stock_code(stock_code)
    if not code:
        return 0
    rule_ph = ",".join("?" for _ in SELL_RULES)
    status_ph = ",".join("?" for _ in ACTIVE_ORPHAN_STATUSES)
    cur.execute(
        f"""
        UPDATE threshold_state
           SET status = ?,
               notes = CASE
                   WHEN notes IS NULL OR notes = '' THEN ?
                   ELSE notes || ' | ' || ?
               END,
               updated_at = CURRENT_TIMESTAMP
         WHERE status IN ({status_ph})
           AND rule_name IN ({rule_ph})
           AND (
                stock_code = ?
                OR stock_code = ?
                OR REPLACE(UPPER(stock_code), 'SH', '') = ?
                OR REPLACE(UPPER(stock_code), 'SZ', '') = ?
                OR REPLACE(UPPER(stock_code), 'BJ', '') = ?
           )
        """,
        (
            final_status,
            note,
            note,
            *ACTIVE_ORPHAN_STATUSES,
            *SELL_RULES,
            code,
            stock_code,
            code,
            code,
            code,
        ),
    )
    return int(cur.rowcount or 0)


def build_sell_signal_reason(
    rule_name: str,
    trigger_price: Optional[float] = None,
    volume: Optional[float] = None,
    extra: str = "",
) -> str:
    """生成标准化 SELL signal_reason：``规则名|触发价|量能``。

    任一字段缺失时跳过该段，但 rule_name 必填（缺失时用 'unknown' 占位以保证非空）。
    """
    rule = (rule_name or "unknown").strip()
    parts = [rule]
    if trigger_price is not None:
        try:
            parts.append(f"触发价{float(trigger_price):.3f}")
        except (TypeError, ValueError):
            pass
    if volume is not None:
        try:
            parts.append(f"量能{int(float(volume))}")
        except (TypeError, ValueError):
            pass
    if extra:
        parts.append(str(extra).strip())
    return "|".join(p for p in parts if p)


@dataclass
class SellReconResult:
    account_id: int
    account_label: str
    day: str
    sell_trades: list = field(default_factory=list)          # 当日所有 SELL 成交
    orphan_sells: list = field(default_factory=list)         # 无对应信号 / signal_reason 为空
    unmatched_signals: list = field(default_factory=list)    # 有卖出信号但无成交

    @property
    def has_gap(self) -> bool:
        return bool(self.orphan_sells or self.unmatched_signals)

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "account_label": self.account_label,
            "day": self.day,
            "sell_trade_count": len(self.sell_trades),
            "orphan_sells": self.orphan_sells,
            "unmatched_signals": self.unmatched_signals,
            "has_gap": self.has_gap,
        }


def _table_exists(cur, name: str) -> bool:
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def reconcile_sell_signals(day: str, db_path: Path, account_id: int) -> SellReconResult:
    """对账某账户当日 SELL 成交与 threshold_state 卖出信号。

    缺口判定：
      - orphan_sells: SELL 成交存在，但 (a) signal_reason 为空/NULL，或
        (b) threshold_state 中该 stock_code 当日无任何 armed/confirmed/executed 的卖出规则。
      - unmatched_signals: threshold_state 当日有卖出规则进入 armed/confirmed/executed，
        但当日无对应 SELL 成交。
    """
    db_path = Path(db_path)
    label = ACCOUNT_LABELS.get(account_id, str(account_id))
    result = SellReconResult(account_id=account_id, account_label=label, day=day)
    if not db_path.exists():
        return result
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        if not _table_exists(cur, "sim_trades"):
            return result

        sells = cur.execute(
            """
            SELECT id, account_id, stock_code, stock_name, trade_date, direction,
                   price, quantity, signal_reason
            FROM sim_trades
            WHERE account_id=? AND trade_date=? AND direction='SELL'
            ORDER BY id
            """,
            (account_id, day),
        ).fetchall()
        result.sell_trades = [dict(r) for r in sells]

        # threshold_state 当日卖出信号（按 stock_code 索引）
        signals_by_code: dict[str, list] = {}
        if _table_exists(cur, "threshold_state"):
            placeholders = ",".join("?" for _ in SELL_RULES)
            st_placeholders = ",".join("?" for _ in ARMED_STATUSES)
            sig_rows = cur.execute(
                f"""
                SELECT stock_code, stock_name, rule_name, rule_threshold, status,
                       first_hit_date, first_hit_price, first_hit_time, notes,
                       next_day_confirmed_at, close_confirmed_at
                FROM threshold_state
                WHERE rule_name IN ({placeholders})
                  AND status IN ({st_placeholders})
                  AND (first_hit_date=? OR next_day_confirmed_at=? OR close_confirmed_at=?)
                """,
                (*SELL_RULES, *ARMED_STATUSES, day, day, day),
            ).fetchall()
            for r in sig_rows:
                signals_by_code.setdefault(r["stock_code"], []).append(dict(r))

        sold_codes = set()
        for s in result.sell_trades:
            code = s["stock_code"]
            sold_codes.add(code)
            reason = (s.get("signal_reason") or "").strip()
            sigs = signals_by_code.get(code, [])
            if not reason:
                result.orphan_sells.append({
                    **s,
                    "gap_kind": "missing_signal_reason",
                    "candidate_signals": sigs,
                })
            elif not sigs:
                result.orphan_sells.append({
                    **s,
                    "gap_kind": "no_threshold_state_record",
                    "candidate_signals": [],
                })

        # 有卖出信号但当日无成交
        for code, sigs in signals_by_code.items():
            if code not in sold_codes:
                result.unmatched_signals.append({
                    "stock_code": code,
                    "stock_name": sigs[0].get("stock_name"),
                    "signals": sigs,
                })
        return result
    finally:
        conn.close()


def audit_all_accounts(day: str, db_path: Path,
                       account_ids: tuple[int, ...] = (1, 2)) -> dict[int, SellReconResult]:
    """对多个账户分别对账，返回 {account_id: SellReconResult}。"""
    return {aid: reconcile_sell_signals(day, db_path, aid) for aid in account_ids}


def format_recon_report(results: dict[int, SellReconResult]) -> str:
    """把对账结果渲染成可读文本（用于复盘脚本 / 企微告警）。"""
    lines = []
    any_gap = False
    for aid in sorted(results):
        r = results[aid]
        header = f"[{r.account_label}#{aid}] 当日SELL成交 {len(r.sell_trades)} 笔"
        if not r.has_gap:
            lines.append(f"✅ {header}，信号-成交链路完整")
            continue
        any_gap = True
        lines.append(f"⚠️ {header}，发现缺口：")
        for o in r.orphan_sells:
            kind = "signal_reason为空" if o["gap_kind"] == "missing_signal_reason" else "无threshold_state信号记录"
            lines.append(
                f"  • SELL {o['stock_name'] or ''}({o['stock_code']}) "
                f"{o['price']}x{o['quantity']} → {kind}"
            )
        for u in r.unmatched_signals:
            rules = ",".join(s["rule_name"] for s in u["signals"])
            lines.append(
                f"  • 信号未成交 {u['stock_name'] or ''}({u['stock_code']}) "
                f"规则[{rules}] armed/confirmed 但当日无SELL成交"
            )
    if not any_gap and not lines:
        lines.append("✅ 无SELL成交，无需对账")
    return "\n".join(lines)
