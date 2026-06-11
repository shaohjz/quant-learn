"""Trading discipline check-in and execution scoring (REQ-027).

The module keeps the feature deliberately data-driven:
- Before market: create/update a daily discipline plan ("check-in").
- After market: score actual ``sim_trades`` and positions against that plan.
- Daily review can render the score without knowing scoring internals.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import date
from typing import Any


@dataclass
class DisciplinePlan:
    account_id: int = 1
    trade_date: str = ""
    max_daily_trades: int = 10
    max_buy_trades: int | None = None
    max_sell_trades: int | None = None
    max_turnover_pct: float = 0.50
    max_single_position_pct: float = 0.35
    min_cash_pct: float = 0.10
    no_chase: bool = True
    notes: str = ""
    source: str = "default"


def _day_str(day: str | date) -> str:
    return day.isoformat() if isinstance(day, date) else str(day)


def _pct(value: Any, default: float) -> float:
    """Normalize pct values: accepts 0.15 or 15 as 15%."""
    if value is None or value == "":
        return default
    try:
        v = float(value)
    except Exception:
        return default
    return v / 100.0 if abs(v) > 1 else v


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def ensure_trade_discipline_tables(conn: sqlite3.Connection) -> None:
    """Create the REQ-027 tables if missing."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_discipline_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL DEFAULT 1,
            trade_date TEXT NOT NULL,
            max_daily_trades INTEGER,
            max_buy_trades INTEGER,
            max_sell_trades INTEGER,
            max_turnover_pct REAL,
            max_single_position_pct REAL,
            min_cash_pct REAL,
            no_chase INTEGER DEFAULT 1,
            notes TEXT DEFAULT '',
            source TEXT DEFAULT 'manual',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, trade_date)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_discipline_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL DEFAULT 1,
            trade_date TEXT NOT NULL,
            score REAL NOT NULL,
            grade TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            violations_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, trade_date)
        )
        """
    )


def default_plan(account_id: int, trade_date: str | date, config: dict | None = None) -> DisciplinePlan:
    """Build a sensible plan from config when available, otherwise conservative defaults."""
    cfg = config or {}
    risk = cfg.get("risk") or {}
    review = (cfg.get("review") or {}).get("discipline") or {}
    return DisciplinePlan(
        account_id=account_id,
        trade_date=_day_str(trade_date),
        max_daily_trades=int(review.get("max_daily_trades", risk.get("max_daily_trades", 10)) or 10),
        max_buy_trades=_int_or_none(review.get("max_buy_trades")),
        max_sell_trades=_int_or_none(review.get("max_sell_trades")),
        max_turnover_pct=_pct(review.get("max_turnover_pct"), 0.50),
        max_single_position_pct=_pct(
            review.get("max_single_position_pct", risk.get("max_single_position_pct")), 0.35
        ),
        min_cash_pct=_pct(review.get("min_cash_pct", risk.get("min_cash_pct")), 0.10),
        no_chase=bool(review.get("no_chase", True)),
        notes=str(review.get("notes", "")),
        source="default",
    )


def upsert_discipline_plan(
    conn: sqlite3.Connection,
    account_id: int,
    trade_date: str | date,
    **kwargs: Any,
) -> DisciplinePlan:
    """Create/update a pre-market discipline check-in plan."""
    ensure_trade_discipline_tables(conn)
    day = _day_str(trade_date)
    plan = default_plan(account_id, day)
    for key, value in kwargs.items():
        if hasattr(plan, key) and value is not None:
            if key.endswith("_pct"):
                setattr(plan, key, _pct(value, getattr(plan, key)))
            elif key.startswith("max_") and key.endswith("trades"):
                setattr(plan, key, _int_or_none(value))
            elif key == "no_chase":
                setattr(plan, key, bool(value))
            else:
                setattr(plan, key, value)
    plan.source = str(kwargs.get("source") or "manual")

    conn.execute(
        """
        INSERT INTO trade_discipline_plans (
            account_id, trade_date, max_daily_trades, max_buy_trades, max_sell_trades,
            max_turnover_pct, max_single_position_pct, min_cash_pct, no_chase, notes, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, trade_date) DO UPDATE SET
            max_daily_trades=excluded.max_daily_trades,
            max_buy_trades=excluded.max_buy_trades,
            max_sell_trades=excluded.max_sell_trades,
            max_turnover_pct=excluded.max_turnover_pct,
            max_single_position_pct=excluded.max_single_position_pct,
            min_cash_pct=excluded.min_cash_pct,
            no_chase=excluded.no_chase,
            notes=excluded.notes,
            source=excluded.source,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            account_id,
            day,
            plan.max_daily_trades,
            plan.max_buy_trades,
            plan.max_sell_trades,
            plan.max_turnover_pct,
            plan.max_single_position_pct,
            plan.min_cash_pct,
            1 if plan.no_chase else 0,
            plan.notes,
            plan.source,
        ),
    )
    return plan


def get_discipline_plan(
    conn: sqlite3.Connection,
    account_id: int,
    trade_date: str | date,
    config: dict | None = None,
) -> DisciplinePlan:
    ensure_trade_discipline_tables(conn)
    day = _day_str(trade_date)
    row = conn.execute(
        "SELECT * FROM trade_discipline_plans WHERE account_id=? AND trade_date=?",
        (account_id, day),
    ).fetchone()
    if not row:
        return default_plan(account_id, day, config=config)
    data = dict(row)
    return DisciplinePlan(
        account_id=int(data["account_id"]),
        trade_date=data["trade_date"],
        max_daily_trades=int(data["max_daily_trades"] or 10),
        max_buy_trades=_int_or_none(data.get("max_buy_trades")),
        max_sell_trades=_int_or_none(data.get("max_sell_trades")),
        max_turnover_pct=_pct(data.get("max_turnover_pct"), 0.50),
        max_single_position_pct=_pct(data.get("max_single_position_pct"), 0.35),
        min_cash_pct=_pct(data.get("min_cash_pct"), 0.10),
        no_chase=bool(data.get("no_chase", 1)),
        notes=data.get("notes") or "",
        source=data.get("source") or "manual",
    )


def _fetch_dicts(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "E"


def score_trade_discipline(
    conn: sqlite3.Connection,
    account_id: int,
    trade_date: str | date,
    plan: DisciplinePlan | None = None,
    config: dict | None = None,
    persist: bool = True,
) -> dict:
    """Score actual trades/positions against the pre-market discipline plan.

    The score is 0~100 and intentionally transparent: each violated rule deducts
    a fixed number of points and is returned in ``violations``.
    """
    ensure_trade_discipline_tables(conn)
    day = _day_str(trade_date)
    plan = plan or get_discipline_plan(conn, account_id, day, config=config)

    trades = _fetch_dicts(
        conn,
        "SELECT * FROM sim_trades WHERE account_id=? AND trade_date=? ORDER BY id",
        (account_id, day),
    )
    positions = _fetch_dicts(
        conn,
        "SELECT * FROM sim_positions WHERE account_id=? ORDER BY market_value DESC",
        (account_id,),
    )
    account_row = conn.execute("SELECT * FROM sim_account WHERE id=?", (account_id,)).fetchone()
    account = dict(account_row) if account_row else {}

    buy_count = sum(1 for t in trades if str(t.get("direction") or "").upper() == "BUY")
    sell_count = sum(1 for t in trades if str(t.get("direction") or "").upper() == "SELL")
    trade_count = len(trades)
    turnover = sum(float(t.get("amount") or (float(t.get("price") or 0) * int(t.get("quantity") or 0))) for t in trades)
    market_value = sum(float(p.get("market_value") or 0) for p in positions)
    cash = float(account.get("cash") or 0)
    total_assets = float(account.get("total_value") or 0) or (cash + market_value)
    cash_pct = cash / total_assets if total_assets > 0 else 1.0
    turnover_pct = turnover / total_assets if total_assets > 0 else 0.0
    max_single_pct = 0.0
    if total_assets > 0 and positions:
        max_single_pct = max(float(p.get("market_value") or 0) / total_assets for p in positions)

    score = 100.0
    violations: list[dict] = []

    def deduct(points: float, rule: str, message: str) -> None:
        nonlocal score
        score -= points
        violations.append({"rule": rule, "deduct": points, "message": message})

    if plan.max_daily_trades is not None and trade_count > plan.max_daily_trades:
        deduct(25, "max_daily_trades", f"当日交易 {trade_count} 笔 > 纪律上限 {plan.max_daily_trades} 笔")
    if plan.max_buy_trades is not None and buy_count > plan.max_buy_trades:
        deduct(15, "max_buy_trades", f"买入 {buy_count} 笔 > 盘前上限 {plan.max_buy_trades} 笔")
    if plan.max_sell_trades is not None and sell_count > plan.max_sell_trades:
        deduct(10, "max_sell_trades", f"卖出 {sell_count} 笔 > 盘前上限 {plan.max_sell_trades} 笔")
    if turnover_pct > plan.max_turnover_pct:
        deduct(20, "max_turnover_pct", f"成交额占总资产 {turnover_pct*100:.1f}% > 上限 {plan.max_turnover_pct*100:.1f}%")
    if max_single_pct > plan.max_single_position_pct:
        deduct(15, "max_single_position_pct", f"最大单票仓位 {max_single_pct*100:.1f}% > 上限 {plan.max_single_position_pct*100:.1f}%")
    if cash_pct < plan.min_cash_pct:
        deduct(15, "min_cash_pct", f"现金水位 {cash_pct*100:.1f}% < 下限 {plan.min_cash_pct*100:.1f}%")
    if plan.no_chase:
        chase_trades = []
        for t in trades:
            if str(t.get("direction") or "").upper() != "BUY":
                continue
            blob = " ".join(str(t.get(k) or "") for k in ("signal_reason", "signal_detail", "trade_context"))
            if any(keyword in blob for keyword in ("追高", "chase", "冲动", "临时起意")):
                chase_trades.append(t.get("stock_code") or "?")
        if chase_trades:
            deduct(10, "no_chase", "买入记录疑似追高/冲动交易：" + ",".join(chase_trades))

    score = max(0.0, round(score, 1))
    metrics = {
        "trade_count": trade_count,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "turnover": round(turnover, 2),
        "turnover_pct": turnover_pct,
        "cash_pct": cash_pct,
        "max_single_position_pct": max_single_pct,
        "total_assets": total_assets,
    }
    result = {
        "account_id": account_id,
        "trade_date": day,
        "score": score,
        "grade": _grade(score),
        "plan": asdict(plan),
        "metrics": metrics,
        "violations": violations,
    }

    if persist:
        conn.execute(
            """
            INSERT INTO trade_discipline_scores (
                account_id, trade_date, score, grade, plan_json, metrics_json, violations_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, trade_date) DO UPDATE SET
                score=excluded.score,
                grade=excluded.grade,
                plan_json=excluded.plan_json,
                metrics_json=excluded.metrics_json,
                violations_json=excluded.violations_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                account_id,
                day,
                score,
                result["grade"],
                json.dumps(result["plan"], ensure_ascii=False, sort_keys=True),
                json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                json.dumps(violations, ensure_ascii=False, sort_keys=True),
            ),
        )
    return result


def render_discipline_score(result: dict, compact: bool = False) -> str:
    """Render a Markdown section for daily/PM review."""
    if not result:
        return ""
    plan = result.get("plan") or {}
    m = result.get("metrics") or {}
    title = "🧭 交易纪律" if compact else "### 🧭 交易纪律打卡与知行合一评分"
    lines = [title]
    lines.append(f"- 知行合一评分：**{result['score']:.1f}/100（{result['grade']}）**")
    lines.append(
        "- 盘前纪律："
        f"日交易≤{plan.get('max_daily_trades')}笔，"
        f"成交额≤{float(plan.get('max_turnover_pct') or 0)*100:.0f}%资产，"
        f"单票≤{float(plan.get('max_single_position_pct') or 0)*100:.0f}%资产，"
        f"现金≥{float(plan.get('min_cash_pct') or 0)*100:.0f}%"
    )
    lines.append(
        "- 盘后执行："
        f"交易 {m.get('trade_count', 0)} 笔（买 {m.get('buy_count', 0)} / 卖 {m.get('sell_count', 0)}），"
        f"成交额占比 {float(m.get('turnover_pct') or 0)*100:.1f}%，"
        f"现金 {float(m.get('cash_pct') or 0)*100:.1f}%，"
        f"最大单票 {float(m.get('max_single_position_pct') or 0)*100:.1f}%"
    )
    violations = result.get("violations") or []
    if violations:
        limit = 2 if compact else 8
        for v in violations[:limit]:
            lines.append(f"- ⚠️ {v.get('message')}")
        if len(violations) > limit:
            lines.append(f"- … 另有 {len(violations)-limit} 条纪律偏差")
    else:
        lines.append("- ✅ 按原定纪律执行，未发现明显偏差")
    if plan.get("notes") and not compact:
        lines.append(f"- 盘前备注：{plan['notes']}")
    return "\n".join(lines)
