"""scripts/signal_ledger.py — 每日把信号记进台账并回填前瞻收益

反馈闭环的第一步：先有数据。

- `--record`：把当日信号写进 `signal_outcomes`
    · 账户 #3 波段：读 `swing_scan_results`（A~F 全记，含只观察不买的）
    · 账户 #1 阈值：读 `threshold_state`（buy_zone / buy_strong）
- `--backfill`：给历史信号回填 T+1/3/5/10 收益、5日内是否先触止损或止盈

**未成交的信号也记。** 只记成交过的信号会让样本被执行规则自我验证，
永远看不到「当初没买的那些其实更好」。

只写 signal_outcomes 表；不改 sim_trades / sim_positions / config，不下单、不推送。

用法：
  python scripts/signal_ledger.py                      # 记今天 + 回填
  python scripts/signal_ledger.py --date 2026-07-30
  python scripts/signal_ledger.py --backfill-only
  python scripts/signal_ledger.py --record-only --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from quant_core.swing_params import load_swing_params  # noqa: E402
from sim.config_resolver import resolve_db_path  # noqa: E402
from sim.signal_ledger import (  # noqa: E402
    SignalRecord,
    backfill,
    ensure_tables,
    record_signals,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("signal_ledger")

SWING_ACCOUNT_ID = 3
LEARN_ACCOUNT_ID = 1
# 回填要覆盖 10 个交易日的窗口，多取一些日K防节假日。
KLINE_DAYS = 40


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _norm_code(code: str) -> str:
    """统一成 shXXXXXX / szXXXXXX，让台账和行情接口对得上。"""
    raw = str(code or "").strip().lower()
    if raw.startswith(("sh", "sz")):
        return raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) != 6:
        return raw
    return ("sh" if digits.startswith(("5", "6", "9")) else "sz") + digits


def _executed_codes(conn: sqlite3.Connection, account_id: int, day: str) -> set[str]:
    """当日在该账户真实买入过的股票（用于给信号打 executed 标记）。"""
    if not _table_exists(conn, "sim_trades"):
        return set()
    rows = conn.execute(
        "SELECT stock_code FROM sim_trades "
        "WHERE account_id=? AND DATE(trade_date)=? AND UPPER(direction)='BUY'",
        (account_id, day),
    ).fetchall()
    return {_norm_code(r[0]) for r in rows}


def collect_swing_signals(conn: sqlite3.Connection, day: str) -> list[SignalRecord]:
    """账户 #3：从当日扫描结果生成台账行。"""
    if not _table_exists(conn, "swing_scan_results"):
        log.warning("swing_scan_results 表不存在，跳过波段信号")
        return []

    params = load_swing_params()
    fingerprint = params.fingerprint()
    executed = _executed_codes(conn, SWING_ACCOUNT_ID, day)

    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM swing_scan_results WHERE scan_date=?", (day,)
    ).fetchall()

    out: list[SignalRecord] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        data = dict(row)
        code = _norm_code(data.get("stock_code") or "")
        sig_type = str(data.get("signal_type") or "").strip().upper()
        if not code or not sig_type:
            continue
        # 同日同票同型可能因盘中多次扫描重复入库，只留一条。
        if (code, sig_type) in seen:
            continue
        seen.add((code, sig_type))

        score = float(data.get("score") or 0.0)
        executable = sig_type in params.executable_types and score >= params.min_score_buy
        out.append(
            SignalRecord(
                signal_date=day,
                account_id=SWING_ACCOUNT_ID,
                stock_code=code,
                stock_name=str(data.get("stock_name") or ""),
                signal_type=sig_type,
                strategy="swing",
                score=score,
                ref_price=float(data.get("price") or 0.0),
                net_rr=_maybe_float(data.get("net_rr")),
                upside_pct=_maybe_float(data.get("upside_pct")),
                downside_pct=_maybe_float(data.get("downside_pct")),
                executable=executable,
                executed=code in executed,
                params_fingerprint=fingerprint,
                extra={"signals": data.get("signals") or ""},
            )
        )
    return out


def collect_threshold_signals(conn: sqlite3.Connection, day: str) -> list[SignalRecord]:
    """账户 #1：从 threshold_state 取当日首次触发的买入类信号。"""
    if not _table_exists(conn, "threshold_state"):
        log.info("threshold_state 表不存在（本地库常见），跳过阈值信号")
        return []

    try:
        from sim.config import get as cfg_get

        buy_strong_enabled = bool(cfg_get("risk.buy_strong_enabled", False))
    except Exception:
        buy_strong_enabled = False

    executed_codes = _executed_codes(conn, LEARN_ACCOUNT_ID, day)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM threshold_state WHERE first_hit_date=?", (day,)
    ).fetchall()

    out: list[SignalRecord] = []
    for row in rows:
        data = dict(row)
        rule = str(data.get("rule_name") or "").strip()
        if rule not in ("buy_zone", "buy_strong"):
            continue  # 卖出类规则不进买入信号台账
        code = _norm_code(data.get("stock_code") or "")
        if not code:
            continue
        executable = rule == "buy_zone" or (rule == "buy_strong" and buy_strong_enabled)
        out.append(
            SignalRecord(
                signal_date=day,
                account_id=LEARN_ACCOUNT_ID,
                stock_code=code,
                stock_name=str(data.get("stock_name") or ""),
                signal_type=rule,
                strategy="threshold",
                ref_price=float(data.get("first_hit_price") or 0.0),
                executable=executable,
                executed=(
                    str(data.get("status") or "").lower() == "executed"
                    or code in executed_codes
                ),
                extra={"rule_threshold": data.get("rule_threshold")},
            )
        )
    return out


def _maybe_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def make_kline_fetcher(days: int = KLINE_DAYS):
    """腾讯前复权日K。前复权用于收益统计口径一致（不是用来撮合的执行价）。"""
    from swing_auto import get_kline

    cache: dict[str, list[dict] | None] = {}

    def fetch(code: str) -> list[dict] | None:
        if code not in cache:
            cache[code] = get_kline(code, days=days)
        return cache[code]

    return fetch


def main() -> int:
    ap = argparse.ArgumentParser(description="信号结果台账：记录 + 回填前瞻收益")
    ap.add_argument("--date", default=date.today().isoformat(), help="信号日期 YYYY-MM-DD")
    ap.add_argument("--db", default=None, help="数据库路径（默认走统一解析）")
    ap.add_argument("--record-only", action="store_true", help="只记录当日信号")
    ap.add_argument("--backfill-only", action="store_true", help="只回填历史信号")
    ap.add_argument("--limit", type=int, default=None, help="回填条数上限（限速用）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    args = ap.parse_args()

    db_path = resolve_db_path(args.db)
    params = load_swing_params()
    log.info("DB=%s 参数层=%s 指纹=%s", db_path, "→".join(params.source_layers), params.fingerprint())

    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        ensure_tables(conn)
        conn.commit()

        do_record = not args.backfill_only
        do_backfill = not args.record_only

        if do_record:
            records = collect_swing_signals(conn, args.date)
            records += collect_threshold_signals(conn, args.date)
            log.info("%s 采集到 %d 条信号", args.date, len(records))
            for rec in records:
                log.info(
                    "  %s %s %s score=%s ref=%.3f 可成交=%s 已成交=%s",
                    rec.strategy,
                    rec.stock_code,
                    rec.signal_type,
                    rec.score,
                    rec.ref_price,
                    rec.executable,
                    rec.executed,
                )
            if args.dry_run:
                log.info("dry-run：不写库")
            elif records:
                stats = record_signals(conn, records)
                log.info("写入完成：新增 %d 更新 %d", stats["inserted"], stats["updated"])

        if do_backfill:
            if args.dry_run:
                log.info("dry-run：跳过回填")
            else:
                stats = backfill(
                    conn,
                    make_kline_fetcher(),
                    stop_loss_pct=params.stop_loss_pct,
                    take_profit_pct=params.take_profit_pct,
                    as_of=args.date,
                    limit=args.limit,
                )
                log.info(
                    "回填完成：扫描 %d 更新 %d 完成 %d 无行情 %d",
                    stats["scanned"],
                    stats["updated"],
                    stats["completed"],
                    stats["no_data"],
                )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
