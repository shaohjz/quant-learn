"""review/funnel.py — 信号漏斗：一只票从被扫到成交，中途死在哪一层。

只看「今天成交 0 笔」学不到任何东西 —— 不知道是市场没机会、信号太严、还是
被自己的仓位上限挡住了。把每层的存活数拉出来，瓶颈才会自己浮出来。

数据源是 swing_pool_builder 和 swing_daily_report 已经在写的 JSON 产物，
不额外埋点，因此历史数据也能直接回看。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class FunnelStage:
    key: str
    label: str
    count: int | None
    note: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "count": self.count, "note": self.note}


@dataclass
class DayFunnel:
    day: str
    stages: list[FunnelStage] = field(default_factory=list)
    positions: int | None = None
    max_positions: int | None = None
    cash: float | None = None
    total_value: float | None = None
    fills: int = 0
    advice: int = 0
    advice_hints: list[str] = field(default_factory=list)
    data_mode: str = ""
    advice_not_filled: bool = False
    blocked_by_position_cap: bool = False
    pool_fallback: bool = False
    legacy_schema: bool = False

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "stages": [s.to_dict() for s in self.stages],
            "positions": self.positions,
            "max_positions": self.max_positions,
            "cash": self.cash,
            "total_value": self.total_value,
            "fills": self.fills,
            "advice": self.advice,
            "advice_hints": self.advice_hints,
            "data_mode": self.data_mode,
            "advice_not_filled": self.advice_not_filled,
            "blocked_by_position_cap": self.blocked_by_position_cap,
            "pool_fallback": self.pool_fallback,
            "legacy_schema": self.legacy_schema,
        }


@dataclass
class FunnelReport:
    days: list[DayFunnel] = field(default_factory=list)
    lookback: int = 0
    zero_fill_streak: int = 0
    blocked_days: int = 0
    advice_not_filled_days: int = 0
    days_with_advice: int = 0
    total_fills: int = 0
    capital_cap_pct: float | None = None
    idle_cash_pct: float | None = None
    instrumentation_gaps: list[str] = field(default_factory=list)

    @property
    def latest(self) -> DayFunnel | None:
        return self.days[-1] if self.days else None

    def to_dict(self) -> dict:
        return {
            "lookback": self.lookback,
            "zero_fill_streak": self.zero_fill_streak,
            "blocked_days": self.blocked_days,
            "advice_not_filled_days": self.advice_not_filled_days,
            "days_with_advice": self.days_with_advice,
            "total_fills": self.total_fills,
            "capital_cap_pct": round(self.capital_cap_pct, 2) if self.capital_cap_pct is not None else None,
            "idle_cash_pct": round(self.idle_cash_pct, 2) if self.idle_cash_pct is not None else None,
            "instrumentation_gaps": self.instrumentation_gaps,
            "days": [d.to_dict() for d in self.days],
        }


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_fill_counts(root: Path, account_id: int, db_path: Path | str | None = None) -> dict[str, int]:
    """每个交易日的真实成交笔数。

    不能用 swing_daily 的 ``fills``：那只是 swing_daily_report 本次执行撮合的单子，
    盘中 swing_intraday_watch 成交的不在里面。2026-08-03 #3 明明买了中国太保和
    三一重工两笔，swing_daily 的 fills 却是 0，漏斗据此报了「连续 13 天 0 成交」——
    结论完全反了。

    优先读 DB（权威），DB 里没有再回退台账 JSON（git 里跟着仓库走，开发机也能看）。
    """
    counts: dict[str, int] = {}

    if db_path is not None:
        try:
            import sqlite3

            conn = sqlite3.connect(str(db_path), timeout=30)
            try:
                rows = conn.execute(
                    "SELECT trade_date, COUNT(*) FROM sim_trades WHERE account_id=? GROUP BY trade_date",
                    (account_id,),
                ).fetchall()
                counts = {str(r[0])[:10]: int(r[1]) for r in rows if r[0]}
            finally:
                conn.close()
        except Exception:
            counts = {}

    if counts:
        return counts

    journal = root / "pm" / "trade_journal"
    if not journal.exists():
        return {}
    for path in journal.glob("*.json"):
        data = _read_json(path)
        if not data:
            continue
        accounts = data.get("accounts") or []
        if isinstance(accounts, dict):
            accounts = list(accounts.values())
        for acct in accounts:
            if not isinstance(acct, dict) or acct.get("account_id") != account_id:
                continue
            counts[path.stem] = len(acct.get("trades") or [])
    return counts


def _collect_days(pool_dir: Path, as_of: date | None, lookback: int) -> list[str]:
    days = sorted(p.stem for p in pool_dir.glob("*.json") if p.stem[:1].isdigit())
    if as_of is not None:
        cutoff = as_of.isoformat()
        days = [d for d in days if d <= cutoff]
    return days[-lookback:] if lookback > 0 else days


def build_swing_funnel(
    root: Path | None = None,
    as_of: date | None = None,
    lookback: int = 10,
    max_positions: int | None = None,
    single_budget: float | None = None,
    initial_cash: float | None = None,
    fill_counts: dict[str, int] | None = None,
) -> FunnelReport:
    """重建 #3 波段链路的漏斗。

    max_positions / single_budget / initial_cash 由调用方从 review.spec 传入，
    这样「资金利用率上限」算的是策略真实参数，不是这里再抄一遍常量。

    fill_counts 是当日真实成交笔数（见 load_fill_counts）；不传则退回
    swing_daily 的 fills 字段，那个口径漏盘中成交，只适合没有台账时用。
    """
    root = root or PROJECT_ROOT
    pool_dir = root / "output" / "swing_pool"
    daily_dir = root / "output" / "swing_daily"

    report = FunnelReport(lookback=lookback)
    if not pool_dir.exists():
        report.instrumentation_gaps.append("output/swing_pool/ 不存在，池子漏斗无法重建")
        return report

    for day in _collect_days(pool_dir, as_of, lookback):
        pool = _read_json(pool_dir / f"{day}.json") or {}
        daily = _read_json(daily_dir / f"{day}.json")

        has_score_stage = "above_min_score" in pool
        above = pool.get("above_min_score")
        top = pool.get("top")
        df = DayFunnel(
            day=day,
            data_mode=str(pool.get("data_mode") or ""),
            legacy_schema=not has_score_stage,
            stages=[
                FunnelStage("universe", "宽基扫描", pool.get("universe_scanned")),
                FunnelStage("candidates", "过硬过滤", pool.get("candidates"), "价格/成交额/ATR/振幅"),
                FunnelStage("above_min_score", "过稳定分线", above,
                            "" if has_score_stage else "该版本未记录此层"),
                FunnelStage("pool", "入池", top, "按稳定分截断到池子上限"),
            ],
        )
        # 只有确实记录了「过线 0 只」才算兜底。字段不存在是旧版本没埋点，
        # 把埋点缺失当成策略异常会让整份报告失去可信度。
        df.pool_fallback = has_score_stage and bool(top) and above == 0

        if daily is None:
            df.stages.append(FunnelStage("fills", "模拟成交", None, "当日无波段日报"))
            report.days.append(df)
            continue

        advice = daily.get("advice") or []
        fills = daily.get("fills") or []
        positions = daily.get("positions") or []
        df.advice = len(advice)
        # 台账/DB 的当日成交才是全量；swing_daily 的 fills 漏盘中成交
        df.fills = fill_counts.get(day, 0) if fill_counts is not None else len(fills)
        df.positions = len(positions)
        df.max_positions = max_positions
        df.cash = daily.get("cash")
        df.total_value = daily.get("total")
        df.advice_hints = [str(a.get("hint") or "") for a in advice if isinstance(a, dict)]
        df.stages.append(FunnelStage("advice", "产生买点建议", df.advice))
        df.stages.append(FunnelStage("fills", "模拟成交", df.fills))

        # 「出了买点却没成交」是当天的客观事实，与今天的参数无关，回看时不会变。
        df.advice_not_filled = df.advice > 0 and df.fills == 0
        # 归因到仓位上限则要用参数判定。注意这里用的是**当前**上限：
        # 调大上限后历史天数会不再命中，那读作「按现在的配置不会再被挡」，
        # 而不是「当时没被挡」—— 当时挡没挡看 advice_not_filled。
        if max_positions is not None:
            df.blocked_by_position_cap = df.advice_not_filled and df.positions >= max_positions

        report.days.append(df)

    scored = [d for d in report.days if d.fills is not None]
    report.total_fills = sum(d.fills for d in scored)
    report.days_with_advice = sum(1 for d in report.days if d.advice > 0)
    report.blocked_days = sum(1 for d in report.days if d.blocked_by_position_cap)
    report.advice_not_filled_days = sum(1 for d in report.days if d.advice_not_filled)

    streak = 0
    for d in reversed(report.days):
        if d.fills == 0:
            streak += 1
        else:
            break
    report.zero_fill_streak = streak

    if max_positions and single_budget and initial_cash:
        report.capital_cap_pct = max_positions * single_budget / initial_cash * 100.0
    latest = report.latest
    if latest and latest.cash is not None and latest.total_value:
        report.idle_cash_pct = latest.cash / latest.total_value * 100.0

    # 池子建好之后、信号扫描之前的那一段没有埋点，无法回答「50 只里几只出了信号」
    report.instrumentation_gaps.append(
        "池内扫描层无埋点：不知道入池 N 只里有几只出信号、几只因 A/B 类型或分数线被拒。"
        "swing_daily_report 落 scanned/signaled/executable 三个计数即可补上。"
    )
    return report
