"""sim/signal_ledger.py — 信号结果台账（策略反馈闭环的地基）

问题：信号每天在发，成交每天在记，但**没人记录「这个信号后来怎么样了」**。
`swing_scan_results` 只有当日快照，`sim_trades` 只有成交过的那几笔，
于是「A 类信号最近 60 天到底赚不赚」这种问题永远答不出来，
PromotionGate 也只能因为 closed_trades=0 一直阻断。

本模块建 `signal_outcomes` 表：每个信号一行，之后按交易日回填 T+1/3/5/10 收益。

关键设计：**未成交的信号也记**。C/D/E/F 当前只观察不买，
它们的前瞻收益是唯一能回答「当初不买对不对」的反事实样本；
只记成交过的信号会让样本被执行规则自我验证（幸存者偏差）。

只写本表，不碰 sim_trades / sim_positions / config。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable, Sequence

# 回填的前瞻窗口（交易日）。5 日为主口径：波段持有期设计是 1-5 天。
FORWARD_HORIZONS = (1, 3, 5, 10)
MAX_HORIZON = max(FORWARD_HORIZONS)

# outcome_status 取值
STATUS_PENDING = "pending"
STATUS_PARTIAL = "partial"
STATUS_COMPLETE = "complete"


@dataclass
class SignalRecord:
    """一条待记账的信号。ref_price 是信号触发当时的参考价，前瞻收益都以它为基准。"""

    signal_date: str
    account_id: int
    stock_code: str
    signal_type: str
    strategy: str
    stock_name: str = ""
    score: float | None = None
    ref_price: float = 0.0
    net_rr: float | None = None
    upside_pct: float | None = None
    downside_pct: float | None = None
    executable: bool = False
    executed: bool = False
    params_fingerprint: str = ""
    extra: dict = field(default_factory=dict)


def ensure_tables(conn: sqlite3.Connection) -> None:
    """幂等建表 + 补列。旧库升级安全。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signal_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_date TEXT NOT NULL,
            account_id INTEGER NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            signal_type TEXT NOT NULL,
            strategy TEXT NOT NULL,
            score REAL,
            ref_price REAL,
            net_rr REAL,
            upside_pct REAL,
            downside_pct REAL,
            executable INTEGER DEFAULT 0,
            executed INTEGER DEFAULT 0,
            fwd_1d REAL,
            fwd_3d REAL,
            fwd_5d REAL,
            fwd_10d REAL,
            fwd_max_gain_5d REAL,
            fwd_max_draw_5d REAL,
            hit_take_profit_5d INTEGER,
            hit_stop_5d INTEGER,
            bars_filled INTEGER DEFAULT 0,
            outcome_status TEXT DEFAULT 'pending',
            last_backfill_date TEXT,
            params_fingerprint TEXT,
            extra TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (signal_date, account_id, stock_code, signal_type)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_outcomes_date ON signal_outcomes(signal_date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_outcomes_status ON signal_outcomes(outcome_status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signal_outcomes_type ON signal_outcomes(strategy, signal_type)"
    )


def record_signals(conn: sqlite3.Connection, records: Iterable[SignalRecord]) -> dict:
    """写入信号。同一(日期,账户,代码,信号类型)重复调用只更新元数据，不重置已回填的收益。"""
    ensure_tables(conn)
    inserted = 0
    updated = 0
    for rec in records:
        if not rec.stock_code or not rec.signal_type:
            continue
        row = conn.execute(
            "SELECT id FROM signal_outcomes "
            "WHERE signal_date=? AND account_id=? AND stock_code=? AND signal_type=?",
            (rec.signal_date, rec.account_id, rec.stock_code, rec.signal_type),
        ).fetchone()
        payload = (
            rec.stock_name,
            rec.score,
            rec.ref_price,
            rec.net_rr,
            rec.upside_pct,
            rec.downside_pct,
            1 if rec.executable else 0,
            1 if rec.executed else 0,
            rec.params_fingerprint,
            json.dumps(rec.extra, ensure_ascii=False) if rec.extra else None,
        )
        if row:
            # executed 只允许 0→1：盘中提醒未成交、收盘补漏成交的情况要能升级。
            conn.execute(
                """
                UPDATE signal_outcomes SET
                    stock_name=?, score=?, ref_price=?, net_rr=?, upside_pct=?,
                    downside_pct=?, executable=?, executed=MAX(executed, ?),
                    params_fingerprint=?, extra=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (*payload, row[0]),
            )
            updated += 1
        else:
            conn.execute(
                """
                INSERT INTO signal_outcomes
                (signal_date, account_id, stock_code, signal_type, strategy,
                 stock_name, score, ref_price, net_rr, upside_pct, downside_pct,
                 executable, executed, params_fingerprint, extra)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    rec.signal_date,
                    rec.account_id,
                    rec.stock_code,
                    rec.signal_type,
                    rec.strategy,
                    *payload,
                ),
            )
            inserted += 1
    conn.commit()
    return {"inserted": inserted, "updated": updated}


def compute_forward_returns(
    ref_price: float,
    future_bars: Sequence[dict],
    stop_loss_pct: float,
    take_profit_pct: float,
) -> dict:
    """从信号日之后的日K算前瞻收益。

    `future_bars` 必须是**信号日之后**按日期升序的 bar（不含信号日自身），
    每个 bar 需含 close/high/low。ref_price 为信号参考价。

    止损/止盈命中用 high/low 判断而非 close：波段规则是盘中触价即处置，
    只看收盘会系统性低估止损命中率，让策略显得比实际温和。
    """
    if ref_price <= 0:
        return {"bars_filled": 0}

    out: dict = {"bars_filled": min(len(future_bars), MAX_HORIZON)}
    for h in FORWARD_HORIZONS:
        if len(future_bars) >= h:
            close = float(future_bars[h - 1].get("close") or 0.0)
            if close > 0:
                out[f"fwd_{h}d"] = (close - ref_price) / ref_price

    window = future_bars[:5]
    if window:
        highs = [float(b.get("high") or 0.0) for b in window]
        lows = [float(b.get("low") or 0.0) for b in window]
        highs = [v for v in highs if v > 0]
        lows = [v for v in lows if v > 0]
        if highs:
            out["fwd_max_gain_5d"] = (max(highs) - ref_price) / ref_price
        if lows:
            out["fwd_max_draw_5d"] = (min(lows) - ref_price) / ref_price

        # 先触止损还是先触止盈，按 bar 顺序判定；同一 bar 内两者都触及时保守算止损先到。
        hit_tp = 0
        hit_sl = 0
        for bar in window:
            high = float(bar.get("high") or 0.0)
            low = float(bar.get("low") or 0.0)
            if low > 0 and low <= ref_price * (1.0 - stop_loss_pct):
                hit_sl = 1
                break
            if high > 0 and high >= ref_price * (1.0 + take_profit_pct):
                hit_tp = 1
                break
        out["hit_stop_5d"] = hit_sl
        out["hit_take_profit_5d"] = hit_tp
    return out


def _status_for(bars_filled: int) -> str:
    if bars_filled >= MAX_HORIZON:
        return STATUS_COMPLETE
    if bars_filled > 0:
        return STATUS_PARTIAL
    return STATUS_PENDING


def pending_signals(conn: sqlite3.Connection, limit: int | None = None) -> list[dict]:
    """取还没填满 10 个交易日的信号。complete 的不再重复拉行情。"""
    ensure_tables(conn)
    sql = (
        "SELECT * FROM signal_outcomes WHERE outcome_status != ? "
        "ORDER BY signal_date DESC, stock_code ASC"
    )
    params: list = [STATUS_COMPLETE]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def backfill(
    conn: sqlite3.Connection,
    kline_fetcher: Callable[[str], list[dict] | None],
    stop_loss_pct: float,
    take_profit_pct: float,
    as_of: str | None = None,
    limit: int | None = None,
) -> dict:
    """回填前瞻收益。

    `kline_fetcher(stock_code)` 返回按日期升序的日K列表（含 date/close/high/low）。
    按股票分组只取一次行情，避免同日多信号重复打接口。
    """
    ensure_tables(conn)
    as_of = as_of or date.today().isoformat()
    rows = pending_signals(conn, limit=limit)
    if not rows:
        return {"scanned": 0, "updated": 0, "completed": 0, "no_data": 0}

    by_code: dict[str, list[dict]] = {}
    for row in rows:
        by_code.setdefault(row["stock_code"], []).append(row)

    updated = completed = no_data = 0
    for code, code_rows in by_code.items():
        bars = kline_fetcher(code)
        if not bars:
            no_data += 1
            continue
        bars = sorted(bars, key=lambda b: str(b.get("date") or ""))
        for row in code_rows:
            sig_date = str(row["signal_date"])
            future = [b for b in bars if str(b.get("date") or "") > sig_date]
            if not future:
                continue
            metrics = compute_forward_returns(
                float(row["ref_price"] or 0.0),
                future,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )
            bars_filled = int(metrics.get("bars_filled") or 0)
            if bars_filled <= int(row["bars_filled"] or 0) and row["outcome_status"] != STATUS_PENDING:
                continue
            status = _status_for(bars_filled)
            conn.execute(
                """
                UPDATE signal_outcomes SET
                    fwd_1d=?, fwd_3d=?, fwd_5d=?, fwd_10d=?,
                    fwd_max_gain_5d=?, fwd_max_draw_5d=?,
                    hit_take_profit_5d=?, hit_stop_5d=?,
                    bars_filled=?, outcome_status=?, last_backfill_date=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    metrics.get("fwd_1d"),
                    metrics.get("fwd_3d"),
                    metrics.get("fwd_5d"),
                    metrics.get("fwd_10d"),
                    metrics.get("fwd_max_gain_5d"),
                    metrics.get("fwd_max_draw_5d"),
                    metrics.get("hit_take_profit_5d"),
                    metrics.get("hit_stop_5d"),
                    bars_filled,
                    status,
                    as_of,
                    row["id"],
                ),
            )
            updated += 1
            if status == STATUS_COMPLETE:
                completed += 1
    conn.commit()
    return {
        "scanned": len(rows),
        "updated": updated,
        "completed": completed,
        "no_data": no_data,
    }


def fetch_outcomes(
    conn: sqlite3.Connection,
    since: str | None = None,
    strategy: str | None = None,
) -> list[dict]:
    """读台账，供记分卡统计。"""
    ensure_tables(conn)
    sql = "SELECT * FROM signal_outcomes WHERE 1=1"
    params: list = []
    if since:
        sql += " AND signal_date >= ?"
        params.append(since)
    if strategy:
        sql += " AND strategy = ?"
        params.append(strategy)
    sql += " ORDER BY signal_date ASC"
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
