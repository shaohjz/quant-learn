"""research/strategy_scorecard.py — 每日策略记分卡（只读统计 + 漂移告警）

回答一个到目前为止答不出来的问题：**策略在变好还是变坏。**

输入是 `signal_outcomes` 台账行，输出分信号类型的滚动统计与告警。
纯计算，不读 DB、不写文件、不碰配置，方便单测。

两个刻意的口径选择：

- 主口径用 **5 日前瞻收益**，因为波段设计持有期就是 1-5 天；
  10 日只作参考，避免用一个策略从没打算持有的窗口去判它死活。
- 同时统计 **executable 与非 executable**。C/D/E/F 当前只观察不买，
  它们的收益是判断「当初不买对不对」的唯一反事实证据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Sequence

# 少于这个样本量的分组不出告警：A股日频信号噪声大，小样本翻正负是常态。
DEFAULT_MIN_SAMPLES = 20
# 非可成交类型要比最佳可成交类型强出这么多（绝对百分点）才值得提「考虑纳入」。
COUNTERFACTUAL_EDGE = 0.01
# 止损命中率超过止盈命中率这个倍数才告警。
STOP_DOMINANCE_RATIO = 1.5


@dataclass
class GroupStats:
    strategy: str
    signal_type: str
    executable: bool
    samples: int = 0
    matured: int = 0
    win_rate: float | None = None
    mean_fwd_5d: float | None = None
    median_fwd_5d: float | None = None
    mean_fwd_1d: float | None = None
    mean_fwd_10d: float | None = None
    take_profit_hit_rate: float | None = None
    stop_hit_rate: float | None = None
    mean_max_gain_5d: float | None = None
    mean_max_draw_5d: float | None = None
    executed: int = 0

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "signal_type": self.signal_type,
            "executable": self.executable,
            "samples": self.samples,
            "matured": self.matured,
            "win_rate": self.win_rate,
            "mean_fwd_5d": self.mean_fwd_5d,
            "median_fwd_5d": self.median_fwd_5d,
            "mean_fwd_1d": self.mean_fwd_1d,
            "mean_fwd_10d": self.mean_fwd_10d,
            "take_profit_hit_rate": self.take_profit_hit_rate,
            "stop_hit_rate": self.stop_hit_rate,
            "mean_max_gain_5d": self.mean_max_gain_5d,
            "mean_max_draw_5d": self.mean_max_draw_5d,
            "executed": self.executed,
        }


@dataclass
class Alarm:
    level: str          # info / warn / critical
    code: str
    message: str
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "context": self.context,
        }


def _mean(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _rate(flags: Sequence[Any]) -> float | None:
    vals = [int(v) for v in flags if v is not None]
    return sum(vals) / len(vals) if vals else None


def trading_dates(rows: Sequence[dict]) -> list[str]:
    """台账里出现过的信号日（升序去重）。滚动窗口按它数，不按自然日。"""
    return sorted({str(r.get("signal_date")) for r in rows if r.get("signal_date")})


def window_rows(rows: Sequence[dict], window: int) -> list[dict]:
    """取最近 `window` 个有信号的交易日。"""
    dates = trading_dates(rows)
    if not dates:
        return []
    keep = set(dates[-window:])
    return [r for r in rows if str(r.get("signal_date")) in keep]


def group_stats(rows: Sequence[dict]) -> list[GroupStats]:
    """按 (strategy, signal_type) 汇总。matured 指已填到 5 日前瞻的样本。"""
    buckets: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (str(row.get("strategy") or "?"), str(row.get("signal_type") or "?"))
        buckets.setdefault(key, []).append(row)

    out: list[GroupStats] = []
    for (strategy, sig_type), group in sorted(buckets.items()):
        matured = [r for r in group if r.get("fwd_5d") is not None]
        fwd5 = [float(r["fwd_5d"]) for r in matured]
        stats = GroupStats(
            strategy=strategy,
            signal_type=sig_type,
            executable=any(int(r.get("executable") or 0) for r in group),
            samples=len(group),
            matured=len(matured),
            executed=sum(int(r.get("executed") or 0) for r in group),
        )
        if fwd5:
            stats.win_rate = sum(1 for v in fwd5 if v > 0) / len(fwd5)
            stats.mean_fwd_5d = _mean(fwd5)
            stats.median_fwd_5d = median(fwd5)
        stats.mean_fwd_1d = _mean([r.get("fwd_1d") for r in group])
        stats.mean_fwd_10d = _mean([r.get("fwd_10d") for r in group])
        stats.take_profit_hit_rate = _rate([r.get("hit_take_profit_5d") for r in group])
        stats.stop_hit_rate = _rate([r.get("hit_stop_5d") for r in group])
        stats.mean_max_gain_5d = _mean([r.get("fwd_max_gain_5d") for r in group])
        stats.mean_max_draw_5d = _mean([r.get("fwd_max_draw_5d") for r in group])
        out.append(stats)
    return out


def detect_alarms(
    stats: Sequence[GroupStats],
    min_samples: int = DEFAULT_MIN_SAMPLES,
    window_label: str = "60d",
) -> list[Alarm]:
    """漂移告警。只在样本足够时开口，避免每天喊狼。"""
    alarms: list[Alarm] = []
    executable = [s for s in stats if s.executable and s.matured >= min_samples]
    ignored = [s for s in stats if not s.executable and s.matured >= min_samples]

    for s in executable:
        if s.mean_fwd_5d is not None and s.mean_fwd_5d < 0:
            alarms.append(
                Alarm(
                    level="critical",
                    code="executable_negative_expectancy",
                    message=(
                        f"{s.strategy} {s.signal_type} 类近 {window_label} "
                        f"5日平均收益 {s.mean_fwd_5d * 100:+.2f}%（{s.matured} 个样本）为负，"
                        f"但它仍是可成交信号"
                    ),
                    context=s.to_dict(),
                )
            )
        if (
            s.stop_hit_rate is not None
            and s.take_profit_hit_rate is not None
            and s.take_profit_hit_rate > 0
            and s.stop_hit_rate > s.take_profit_hit_rate * STOP_DOMINANCE_RATIO
        ):
            alarms.append(
                Alarm(
                    level="warn",
                    code="stop_before_target",
                    message=(
                        f"{s.strategy} {s.signal_type} 类止损先到比例 "
                        f"{s.stop_hit_rate * 100:.0f}% 明显高于止盈 "
                        f"{s.take_profit_hit_rate * 100:.0f}%，止损位可能过紧"
                    ),
                    context=s.to_dict(),
                )
            )

    best_exec = max(
        (s.mean_fwd_5d for s in executable if s.mean_fwd_5d is not None),
        default=None,
    )
    if best_exec is not None:
        for s in ignored:
            if s.mean_fwd_5d is not None and s.mean_fwd_5d > best_exec + COUNTERFACTUAL_EDGE:
                alarms.append(
                    Alarm(
                        level="info",
                        code="ignored_signal_outperforms",
                        message=(
                            f"{s.strategy} {s.signal_type} 类当前只观察不买，但近 {window_label} "
                            f"5日平均收益 {s.mean_fwd_5d * 100:+.2f}% 高于最好的可成交类型 "
                            f"{best_exec * 100:+.2f}%（{s.matured} 个样本），值得进研究队列"
                        ),
                        context=s.to_dict(),
                    )
                )

    exec_signals = sum(s.samples for s in stats if s.executable)
    exec_trades = sum(s.executed for s in stats if s.executable)
    if exec_signals >= min_samples and exec_trades == 0:
        alarms.append(
            Alarm(
                level="critical",
                code="signals_never_executed",
                message=(
                    f"近 {window_label} 有 {exec_signals} 个可成交信号但一笔都没成交，"
                    f"信号到执行链路可能断了"
                ),
                context={"executable_signals": exec_signals},
            )
        )
    return alarms


def staleness_alarm(rows: Sequence[dict], as_of: str, max_gap_days: int = 5) -> Alarm | None:
    """台账停更告警。反馈闭环最常见的死法是没人发现它停了。"""
    dates = trading_dates(rows)
    if not dates:
        return Alarm(
            level="critical",
            code="ledger_empty",
            message="信号台账为空：还没有任何信号被记录，反馈闭环没有数据来源",
        )
    from datetime import date as _date

    try:
        last = _date.fromisoformat(dates[-1])
        gap = (_date.fromisoformat(as_of) - last).days
    except ValueError:
        return None
    if gap > max_gap_days:
        return Alarm(
            level="critical",
            code="ledger_stale",
            message=f"信号台账最后更新于 {dates[-1]}，已停更 {gap} 天",
            context={"last_signal_date": dates[-1], "gap_days": gap},
        )
    return None


def build_scorecard(
    rows: Sequence[dict],
    as_of: str,
    windows: Sequence[int] = (20, 60),
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> dict:
    """完整记分卡。`windows` 单位是「有信号的交易日」个数。"""
    result: dict[str, Any] = {
        "as_of": as_of,
        "read_only": True,
        "total_signals": len(rows),
        "windows": {},
        "alarms": [],
    }

    stale = staleness_alarm(rows, as_of)
    if stale:
        result["alarms"].append(stale.to_dict())

    for window in windows:
        subset = window_rows(rows, window)
        stats = group_stats(subset)
        label = f"{window}d"
        result["windows"][label] = {
            "signal_days": len(trading_dates(subset)),
            "signals": len(subset),
            "groups": [s.to_dict() for s in stats],
            "overall": _overall(subset),
        }
        # 只用最长窗口出告警：短窗噪声大，容易天天变脸。
        if window == max(windows):
            result["alarms"].extend(
                a.to_dict() for a in detect_alarms(stats, min_samples, label)
            )

    result["verdict"] = _verdict(result)
    return result


def _overall(rows: Sequence[dict]) -> dict:
    matured = [r for r in rows if r.get("fwd_5d") is not None]
    fwd5 = [float(r["fwd_5d"]) for r in matured]
    exec_rows = [r for r in rows if int(r.get("executed") or 0)]
    exec_fwd5 = [float(r["fwd_5d"]) for r in exec_rows if r.get("fwd_5d") is not None]
    return {
        "signals": len(rows),
        "matured": len(matured),
        "executed": len(exec_rows),
        "mean_fwd_5d": _mean(fwd5),
        "win_rate": (sum(1 for v in fwd5 if v > 0) / len(fwd5)) if fwd5 else None,
        "executed_mean_fwd_5d": _mean(exec_fwd5),
    }


def _verdict(card: dict) -> str:
    """一句话结论，给企微推送用。"""
    alarms = card.get("alarms") or []
    critical = [a for a in alarms if a["level"] == "critical"]
    if critical:
        return f"异常：{critical[0]['message']}"

    longest = max(card["windows"], key=lambda k: int(k.rstrip("d"))) if card["windows"] else None
    if not longest:
        return "无数据"
    overall = card["windows"][longest]["overall"]
    if overall["matured"] == 0:
        return f"近 {longest} 有 {overall['signals']} 个信号，前瞻收益尚未成熟（需再等几个交易日）"
    mean = overall["mean_fwd_5d"]
    warn = len([a for a in alarms if a["level"] == "warn"])
    tail = f"；{warn} 项预警" if warn else ""
    return (
        f"近 {longest}：{overall['matured']} 个成熟信号，5日平均 {mean * 100:+.2f}%，"
        f"胜率 {overall['win_rate'] * 100:.0f}%，已成交 {overall['executed']} 笔{tail}"
    )


def render_markdown(card: dict) -> str:
    """记分卡 markdown。给人看的那一份。"""
    lines = [
        f"# 策略记分卡 — {card['as_of']}",
        "",
        f"> 只读统计，不改参数、不下单。信号总数 {card['total_signals']}。",
        "",
        f"**结论：{card.get('verdict', '')}**",
        "",
    ]

    alarms = card.get("alarms") or []
    if alarms:
        lines += ["## 告警", ""]
        icon = {"critical": "🚨", "warn": "⚠️", "info": "💡"}
        for a in alarms:
            lines.append(f"- {icon.get(a['level'], '·')} **{a['level']}** [{a['code']}] {a['message']}")
        lines.append("")
    else:
        lines += ["## 告警", "", "- 无", ""]

    for label, block in card.get("windows", {}).items():
        lines += [
            f"## 近 {label}（{block['signal_days']} 个信号日 / {block['signals']} 个信号）",
            "",
            "| 策略 | 型 | 可成交 | 样本 | 成熟 | 胜率 | 5日均收益 | 止盈命中 | 止损命中 | 已成交 |",
            "|------|:--:|:------:|-----:|-----:|-----:|----------:|---------:|---------:|-------:|",
        ]
        for g in block["groups"]:
            lines.append(
                "| {s} | {t} | {e} | {n} | {m} | {w} | {r} | {tp} | {sl} | {x} |".format(
                    s=g["strategy"],
                    t=g["signal_type"],
                    e="✅" if g["executable"] else "—",
                    n=g["samples"],
                    m=g["matured"],
                    w=_pct(g["win_rate"]),
                    r=_pct(g["mean_fwd_5d"], signed=True),
                    tp=_pct(g["take_profit_hit_rate"]),
                    sl=_pct(g["stop_hit_rate"]),
                    x=g["executed"],
                )
            )
        lines.append("")
    return "\n".join(lines)


def _pct(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.2f}%" if signed else f"{value * 100:.0f}%"
