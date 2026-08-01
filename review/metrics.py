"""review/metrics.py — 绩效指标，附带「这个数字能不能信」。

这个项目 14 个交易日只有 57 笔成交。在这种样本量下报一个「胜率 60%」是危险的：
10 笔里赢 6 笔，胜率的 95% 置信区间是 [31%, 83%]，和「什么都不知道」几乎等价。
过去的复盘之所以推不动改进，一半原因是拿这种数字当结论，改完又被下一周的噪音推翻。

所以这里每个统计量都配一个证据等级，日报上直接标出来，
让「样本不够，先别动参数」变成系统说的话，而不是靠人自觉。
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# 证据等级门槛（按已平仓笔数）。和 research/promotion_gate.MIN_CLOSED_TRADES=100
# 是两回事：那个是「能否上实盘」，这个是「能否开口讨论改参数」。
EVIDENCE_TIERS = [
    (0, "none", "无数据", "只能检查链路是否在跑"),
    (1, "anecdote", "轶事", "只能查执行 bug，不能推断策略好坏"),
    (5, "weak", "弱", "能看方向，不足以改参数"),
    (20, "usable", "可用", "可提改参提案，须先影子验证"),
    (50, "solid", "较可靠", "可走晋级流程"),
]


def evidence_level(n: int) -> dict:
    """样本量 → 证据等级。用于给每个结论标注可信度。"""
    tier = EVIDENCE_TIERS[0]
    for t in EVIDENCE_TIERS:
        if n >= t[0]:
            tier = t
    return {"n": n, "level": tier[1], "label": tier[2], "can_do": tier[3]}


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """胜率的 Wilson 置信区间。

    比 normal approximation 在小样本下靠谱得多，且不会给出负下界。
    """
    if n <= 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z / denom * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def breakeven_win_rate(payoff_ratio: float, cost_pct: float = 0.0) -> float | None:
    """给定盈亏比，不亏钱最少需要多少胜率。

    payoff_ratio = 平均盈利 / 平均亏损。cost_pct 是单边成本占均亏的比例。
    5% 止损配 8% 止盈 → 盈亏比 1.6 → 保本胜率 38.5%，这条比任何胜率数字都值得先看。
    """
    if payoff_ratio is None or payoff_ratio <= 0:
        return None
    return (1.0 + cost_pct) / (1.0 + payoff_ratio)


def samples_needed_for_edge(p_hat: float, target: float = 0.5, z: float = 1.96, cap: int = 2000) -> int | None:
    """按当前观测胜率，还要多少笔才能让置信下界越过 target。

    答案通常大得让人清醒：观测 60% 胜率要证明真的强于抛硬币，需要约 90 笔。
    """
    if not 0.0 < p_hat <= 1.0 or p_hat <= target:
        return None
    for n in range(2, cap + 1):
        lo, _ = wilson_interval(round(p_hat * n), n, z)
        if lo > target:
            return n
    return None


@dataclass
class ExpectancyStats:
    n: int = 0
    mean_pct: float = 0.0
    std_pct: float = 0.0
    stderr_pct: float = 0.0
    t_stat: float | None = None
    ci_low_pct: float | None = None
    ci_high_pct: float | None = None
    significant: bool = False

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "mean_pct": round(self.mean_pct, 4),
            "std_pct": round(self.std_pct, 4),
            "stderr_pct": round(self.stderr_pct, 4),
            "t_stat": round(self.t_stat, 3) if self.t_stat is not None else None,
            "ci_low_pct": round(self.ci_low_pct, 4) if self.ci_low_pct is not None else None,
            "ci_high_pct": round(self.ci_high_pct, 4) if self.ci_high_pct is not None else None,
            "significant": self.significant,
        }


def expectancy_stats(returns_pct: Iterable[float], z: float = 1.96) -> ExpectancyStats:
    """单笔收益率的期望及其置信区间。

    significant=True 表示 95% 区间不跨 0，即「平均下来真的在赚」有统计支撑。
    小样本下几乎必然是 False，这正是要显示它的原因。
    """
    vals = [float(v) for v in returns_pct]
    n = len(vals)
    if n == 0:
        return ExpectancyStats()
    mean = sum(vals) / n
    if n == 1:
        return ExpectancyStats(n=1, mean_pct=mean)
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    std = math.sqrt(var)
    se = std / math.sqrt(n)
    lo, hi = mean - z * se, mean + z * se
    return ExpectancyStats(
        n=n,
        mean_pct=mean,
        std_pct=std,
        stderr_pct=se,
        t_stat=(mean / se) if se > 0 else None,
        ci_low_pct=lo,
        ci_high_pct=hi,
        significant=(lo > 0 or hi < 0),
    )


@dataclass
class NavStats:
    days: int = 0
    first_date: str | None = None
    last_date: str | None = None
    total_value: float = 0.0
    cumulative_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    current_drawdown_pct: float = 0.0
    best_day_pct: float = 0.0
    worst_day_pct: float = 0.0
    losing_streak: int = 0

    def to_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def nav_stats(rows: list[dict]) -> NavStats:
    """从 sim_daily_nav 序列算净值侧指标。

    回撤按 total_value 现算而不是读库里的 max_drawdown 列 —— 那一列历史上有写空的记录。
    """
    rows = [r for r in rows if r.get("total_value") is not None]
    rows.sort(key=lambda r: str(r.get("trade_date") or ""))
    if not rows:
        return NavStats()

    values = [float(r["total_value"]) for r in rows]
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak * 100.0)
    cur_dd = (peak - values[-1]) / peak * 100.0 if peak > 0 else 0.0

    daily = [float(r.get("daily_return") or 0.0) for r in rows]
    streak = 0
    for d in reversed(daily):
        if d < 0:
            streak += 1
        else:
            break

    base = values[0]
    cum = float(rows[-1].get("cumulative_return") or 0.0)
    if not cum and base > 0:
        cum = (values[-1] - base) / base * 100.0

    return NavStats(
        days=len(rows),
        first_date=str(rows[0].get("trade_date") or ""),
        last_date=str(rows[-1].get("trade_date") or ""),
        total_value=values[-1],
        cumulative_return_pct=cum,
        max_drawdown_pct=max_dd,
        current_drawdown_pct=cur_dd,
        best_day_pct=max(daily) if daily else 0.0,
        worst_day_pct=min(daily) if daily else 0.0,
        losing_streak=streak,
    )


@dataclass
class AccountPerformance:
    account_id: int
    name: str
    nav: NavStats = field(default_factory=NavStats)
    closed_count: int = 0
    win_count: int = 0
    win_rate_pct: float = 0.0
    win_rate_ci: tuple[float, float] = (0.0, 1.0)
    payoff_ratio: float | None = None
    profit_factor: float | None = None
    net_pnl: float = 0.0
    avg_holding_days: float | None = None
    breakeven_win_rate_pct: float | None = None
    edge_gap_pct: float | None = None
    samples_to_prove: int | None = None
    expectancy: ExpectancyStats = field(default_factory=ExpectancyStats)
    recent_expectancy: ExpectancyStats = field(default_factory=ExpectancyStats)
    by_signal: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=lambda: evidence_level(0))
    closed_trades: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "name": self.name,
            "nav": self.nav.to_dict(),
            "closed_count": self.closed_count,
            "win_count": self.win_count,
            "win_rate_pct": round(self.win_rate_pct, 2),
            "win_rate_ci_pct": [round(self.win_rate_ci[0] * 100, 2), round(self.win_rate_ci[1] * 100, 2)],
            "payoff_ratio": round(self.payoff_ratio, 3) if self.payoff_ratio else None,
            "profit_factor": round(self.profit_factor, 3) if self.profit_factor not in (None, float("inf")) else None,
            "net_pnl": round(self.net_pnl, 2),
            "avg_holding_days": round(self.avg_holding_days, 2) if self.avg_holding_days is not None else None,
            "breakeven_win_rate_pct": (
                round(self.breakeven_win_rate_pct, 2) if self.breakeven_win_rate_pct is not None else None
            ),
            "edge_gap_pct": round(self.edge_gap_pct, 2) if self.edge_gap_pct is not None else None,
            "samples_to_prove": self.samples_to_prove,
            "expectancy": self.expectancy.to_dict(),
            "recent_expectancy": self.recent_expectancy.to_dict(),
            "by_signal": self.by_signal,
            "evidence": self.evidence,
        }


def _conn_factory(db_path: Path | str) -> Callable[[], sqlite3.Connection]:
    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    return factory


def fetch_nav_rows(db_path: Path | str, account_id: int, as_of: date | None = None) -> list[dict]:
    factory = _conn_factory(db_path)
    conn = factory()
    try:
        sql = "SELECT * FROM sim_daily_nav WHERE account_id=?"
        params: list[Any] = [account_id]
        if as_of is not None:
            sql += " AND trade_date<=?"
            params.append(as_of.isoformat())
        sql += " ORDER BY trade_date"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def signal_breakdown(closed: list[dict], min_n: int = 1) -> list[dict]:
    """按开仓信号聚合已实现盈亏，回答「哪个信号在赚钱」。

    每组都带证据等级 —— 分组之后样本只会更小，更需要提醒别当真。
    """
    groups: dict[str, list[dict]] = {}
    for r in closed:
        groups.setdefault(str(r.get("entry_signal") or "unknown"), []).append(r)

    out = []
    for sig, rows in groups.items():
        if len(rows) < min_n:
            continue
        pcts = [float(r.get("pnl_pct") or 0.0) for r in rows]
        wins = sum(1 for r in rows if float(r.get("pnl") or 0.0) > 0)
        est = expectancy_stats(pcts)
        out.append({
            "signal": sig,
            "n": len(rows),
            "win_count": wins,
            "win_rate_pct": round(wins / len(rows) * 100.0, 2),
            "net_pnl": round(sum(float(r.get("pnl") or 0.0) for r in rows), 2),
            "avg_pnl_pct": round(est.mean_pct, 3),
            "expectancy": est.to_dict(),
            "evidence": evidence_level(len(rows)),
        })
    out.sort(key=lambda x: x["net_pnl"])
    return out


def analyze_account(
    db_path: Path | str,
    account_id: int,
    name: str,
    as_of: date | None = None,
    recent_window: int = 20,
) -> AccountPerformance:
    """汇总一个账户的绩效。数据库缺表或为空时返回空结果，不抛异常。

    复盘任务必须在任何环境下都能出报告 —— 本地仓库的 DB 就是空的，
    如果这里炸了，整条链路在开发机上永远验证不了。
    """
    perf = AccountPerformance(account_id=account_id, name=name)
    perf.nav = nav_stats(fetch_nav_rows(db_path, account_id, as_of))

    try:
        from sim.closed_trades import analyze_closed_trades

        result = analyze_closed_trades(account_id, as_of, conn_factory=_conn_factory(db_path))
    except Exception:
        return perf

    summary = result.get("summary") or {}
    closed = result.get("closed_trades") or []
    perf.closed_trades = closed
    perf.closed_count = int(summary.get("closed_count") or 0)
    perf.win_count = int(summary.get("win_count") or 0)
    perf.win_rate_pct = float(summary.get("win_rate") or 0.0)
    perf.win_rate_ci = wilson_interval(perf.win_count, perf.closed_count)
    perf.payoff_ratio = summary.get("payoff_ratio")
    perf.profit_factor = summary.get("profit_factor")
    perf.net_pnl = float(summary.get("net_pnl") or 0.0)
    perf.avg_holding_days = summary.get("avg_holding_days")
    perf.evidence = evidence_level(perf.closed_count)

    if perf.payoff_ratio:
        be = breakeven_win_rate(perf.payoff_ratio)
        if be is not None:
            perf.breakeven_win_rate_pct = be * 100.0
            perf.edge_gap_pct = perf.win_rate_pct - perf.breakeven_win_rate_pct

    if perf.closed_count:
        perf.samples_to_prove = samples_needed_for_edge(perf.win_count / perf.closed_count)

    # closed_trades 已按平仓日倒序，取前 N 就是最近 N 笔
    pcts = [float(r.get("pnl_pct") or 0.0) for r in closed]
    perf.expectancy = expectancy_stats(pcts)
    perf.recent_expectancy = expectancy_stats(pcts[:recent_window])
    perf.by_signal = signal_breakdown(closed)
    return perf
