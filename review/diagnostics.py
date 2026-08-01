"""review/diagnostics.py — 规则化问题发现。

每条 Finding 必须带可复算的证据，不接受「感觉最近不太行」。

layer 是这个模块的核心，它决定一个问题今天能不能动手：

    execution  链路 bug、算术自相矛盾、参数漂移。样本量 1 就能判定，当天就该修。
    signal     信号质量。要 ~20 笔才看得出方向，只能提假设。
    parameter  参数调优。要 50+ 笔且必须回测验证，急不得。

把层级写进数据结构，是为了防止「今天亏了就调止损」这种拿噪音当信号的操作 ——
14 个交易日 57 笔成交的样本量，绝大多数参数改动都只是在拟合运气。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2}
LAYER_LABEL = {
    "execution": "执行层",
    "signal": "信号层",
    "parameter": "参数层",
}
LAYER_HORIZON = {
    "execution": "今天就能改",
    "signal": "攒够样本再判",
    "parameter": "需回测+影子验证",
}


@dataclass
class Finding:
    rule_id: str
    subject: str
    severity: str
    layer: str
    title: str
    evidence: list[str] = field(default_factory=list)
    why: str = ""
    action: str = ""
    data: dict = field(default_factory=dict)

    @property
    def finding_id(self) -> str:
        """跨天稳定，用来追踪「这个问题挂了几天了」。"""
        return f"{self.rule_id}:{self.subject}"

    @property
    def horizon(self) -> str:
        return LAYER_HORIZON.get(self.layer, "")

    def to_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "rule_id": self.rule_id,
            "subject": self.subject,
            "severity": self.severity,
            "layer": self.layer,
            "layer_label": LAYER_LABEL.get(self.layer, self.layer),
            "horizon": self.horizon,
            "title": self.title,
            "evidence": self.evidence,
            "why": self.why,
            "action": self.action,
            "data": self.data,
        }


def _sort(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.layer, f.rule_id))


def _partially_migrated(spec: Any) -> list[Any]:
    """参数同时存在于可配置真源和脚本本地常量 —— 迁移做了一半。"""
    out = []
    for p in spec.params:
        kinds = {r.ref.kind for r in p.refs if r.found}
        if "params" in kinds and "module" in kinds:
            out.append(p)
    return out


def _plain(value: Any) -> Any:
    if isinstance(value, (set, frozenset)):
        return sorted(str(x) for x in value)
    return value


# ───────────────────────── 执行层规则 ─────────────────────────


def check_spec_health(spec: Any) -> list[Finding]:
    """参数在多处定义却对不上，或者根本抽不到 —— 都说明策略真源坏了。"""
    out: list[Finding] = []
    for p in spec.conflicts():
        detail = "；".join(f"{r.ref} = {r.value}" for r in p.refs if r.found)
        out.append(Finding(
            rule_id="spec_conflict",
            subject=f"{spec.strategy_id}.{p.key}",
            severity="P0",
            layer="execution",
            title=f"{spec.name} 参数「{p.label}」多处定义且不一致",
            evidence=[detail],
            why="同一个旋钮有两份真源，改一处另一处照旧生效，盘中和收盘会用不同的规则。",
            action=f"把 {p.key} 收敛到单一定义处，另一处改为引用。",
            data={"param": p.key, "refs": [r.to_dict() for r in p.refs]},
        ))
    for p in _partially_migrated(spec):
        scripts = "、".join(str(r.ref) for r in p.refs if r.ref.kind == "module" and r.found)
        out.append(Finding(
            rule_id="partial_migration",
            subject=f"{spec.strategy_id}.{p.key}",
            severity="P0",
            layer="execution",
            title=f"{spec.name} 参数「{p.label}」已进可配置真源，但执行脚本仍用本地常量",
            evidence=[
                f"真源：{next(str(r.ref) for r in p.refs if r.ref.kind == 'params')} = {p.value}",
                f"仍在用本地常量：{scripts}",
            ],
            why="现在两边值相同所以看不出问题，但一旦通过 YAML 调这个参数，只有读真源的脚本会变，"
                "执行脚本照旧用旧值 —— 自动调参会静默失效。",
            action=f"把上述脚本里的常量改为读 swing_params 的 {p.key}。",
            data={"param": p.key, "value": _plain(p.value)},
        ))

    missing = spec.missing()
    if missing:
        out.append(Finding(
            rule_id="spec_missing",
            subject=spec.strategy_id,
            severity="P1",
            layer="execution",
            title=f"{spec.name} 有 {len(missing)} 个参数抽取不到",
            evidence=[f"{p.key}（{p.label}）← {'、'.join(str(r.ref) for r in p.refs)}" for p in missing],
            why="说明代码里常量被改名或挪走了，策略说明书从这一刻起就是错的。",
            action="核对 review/spec.py 的参数注册表与代码现状。",
            data={"missing": [p.key for p in missing]},
        ))
    return out


def check_capital_structure(spec: Any) -> list[Finding]:
    """仓位上限 × 单笔预算 撑不满本金时，剩下的钱永远不可能被用到。

    这是算术恒等式，不需要任何样本量就能判定，属于最该优先修的一类问题。
    """
    max_pos = spec.value("max_positions") or spec.value("max_total_positions")
    budget = spec.value("single_budget")
    cash = spec.value("initial_cash")
    if not (max_pos and budget and cash):
        return []

    deployable = max_pos * budget
    cap_pct = deployable / cash * 100.0
    if cap_pct >= 80.0:
        return []

    return [Finding(
        rule_id="capital_cap_contradiction",
        subject=spec.strategy_id,
        severity="P0",
        layer="execution",
        title=f"{spec.name} 资金利用率上限只有 {cap_pct:.0f}%",
        evidence=[
            f"最大持仓 {max_pos:g} 只 × 单笔预算 {budget:,.0f} 元 = 最多投入 {deployable:,.0f} 元",
            f"账户本金 {cash:,.0f} 元 → 结构性闲置 {cash - deployable:,.0f} 元（{100 - cap_pct:.0f}%）",
        ],
        why="这不是行情问题，是参数自相矛盾：满仓状态下仍有大量现金取不出来干活，收益率天花板被人为压低。",
        action=f"三选一：单笔预算提到 {cash / max_pos:,.0f} 元、仓位上限提到 {cash / budget:.0f} 只、"
               f"或把账户本金调到 {deployable:,.0f} 元让口径一致。",
        data={"max_positions": max_pos, "single_budget": budget, "initial_cash": cash, "cap_pct": cap_pct},
    )]


def check_funnel(funnel: Any, spec: Any, min_streak: int = 3, min_blocked: int = 2) -> list[Finding]:
    """漏斗层面的执行问题：信号出了但没成交、池子走兜底、埋点缺失。"""
    out: list[Finding] = []
    if not funnel.days:
        return out

    if funnel.blocked_days >= min_blocked:
        blocked = [d for d in funnel.days if d.blocked_by_position_cap]
        out.append(Finding(
            rule_id="position_cap_blocking",
            subject=spec.strategy_id,
            severity="P0",
            layer="execution",
            title=f"{spec.name} 近 {funnel.lookback} 日有 {funnel.blocked_days} 天出了买点却因满仓没成交",
            evidence=[
                f"{d.day}：买点 {d.advice} 个，持仓 {d.positions}/{d.max_positions}，成交 {d.fills}，"
                f"现金 {d.cash:,.0f} 元" for d in blocked
            ],
            why="策略不是没找到机会，是找到了也吃不下。此时再怎么优化选股逻辑都不会改变结果。",
            action="先解决仓位/预算口径（见 capital_cap_contradiction），再谈信号质量。",
            data={"blocked_days": funnel.blocked_days, "days": [d.day for d in blocked]},
        ))

    # 买点没变成成交 —— 与今天的参数无关的事实。放宽仓位上限会让上面那条
    # 归因规则不再命中，但这些天当时确实空过，事实要留在报告里。
    unfilled = [d for d in funnel.days if d.advice_not_filled]
    if not funnel.blocked_days and len(unfilled) >= min_blocked:
        out.append(Finding(
            rule_id="advice_not_filled",
            subject=spec.strategy_id,
            severity="P1",
            layer="execution",
            title=f"{spec.name} 近 {funnel.lookback} 日有 {len(unfilled)} 天出了买点但没成交",
            evidence=[
                f"{d.day}：买点 {d.advice} 个，成交 0，持仓 {d.positions}/{d.max_positions}"
                for d in unfilled[:8]
            ],
            why="按当前仓位上限已不算满仓拦截，所以要另找原因："
                "现金不足、信号在盘中才触发、或收盘补漏没跑到。",
            action="核对 swing_daily_report 的 sim_buy 分支为何跳过；确认现金与整手数是否够一笔。",
            data={"days": [d.day for d in unfilled]},
        ))

    if funnel.zero_fill_streak >= min_streak:
        out.append(Finding(
            rule_id="zero_fill_streak",
            subject=spec.strategy_id,
            severity="P1",
            layer="execution",
            title=f"{spec.name} 连续 {funnel.zero_fill_streak} 个交易日 0 成交",
            evidence=[
                f"回看 {funnel.lookback} 日累计成交 {funnel.total_fills} 笔，其中 {funnel.days_with_advice} 天有买点建议",
            ],
            why="长期不成交等于没有反馈信号：策略好坏无从判断，样本永远攒不起来。",
            action="确认是被仓位挡住还是信号阈值过严；两者都不是才考虑「行情确实没机会」。",
            data={"streak": funnel.zero_fill_streak, "total_fills": funnel.total_fills},
        ))

    fallback_days = [d for d in funnel.days if d.pool_fallback]
    if fallback_days:
        out.append(Finding(
            rule_id="pool_fallback",
            subject=spec.strategy_id,
            severity="P1",
            layer="execution",
            title=f"{spec.name} 有 {len(fallback_days)} 天的池子不是按稳定分选出来的",
            evidence=[f"{d.day}：过稳定分线 0 只，却仍入池 "
                      f"{next((s.count for s in d.stages if s.key == 'pool'), '?')} 只" for d in fallback_days[:6]],
            why="过线 0 只说明当天走了种子池兜底，此时的持仓不代表策略的选股能力，不该计入策略绩效。",
            action="查 swing_pool_builder 的数据源与 stability_score 计算；兜底时应在产物里显式标记。",
            data={"days": [d.day for d in fallback_days]},
        ))

    legacy_days = [d for d in funnel.days if d.legacy_schema]
    if legacy_days:
        out.append(Finding(
            rule_id="funnel_schema_legacy",
            subject=spec.strategy_id,
            severity="P2",
            layer="execution",
            title=f"{spec.name} 有 {len(legacy_days)} 天的池子产物缺「过稳定分线」字段",
            evidence=[f"缺字段的日期：{'、'.join(d.day for d in legacy_days)}"],
            why="那几天的漏斗少一层，不能和新版数据直接比较；也不能据此判断池子是否走了兜底。",
            action="仅影响历史回看，无需修代码；对比漏斗时把这些日期排除。",
            data={"days": [d.day for d in legacy_days]},
        ))

    for gap in funnel.instrumentation_gaps:
        out.append(Finding(
            rule_id="instrumentation_gap",
            subject=spec.strategy_id,
            severity="P2",
            layer="execution",
            title=f"{spec.name} 漏斗埋点缺失",
            evidence=[gap],
            why="缺这一层就说不清「信号少」还是「过滤严」，改阈值只能靠猜。",
            action="在扫描环节落 scanned / signaled / executable 三个计数。",
            data={"gap": gap},
        ))
    return out


def check_nav_freshness(perf: Any, as_of_iso: str, max_stale_days: int = 5) -> list[Finding]:
    """净值断更通常意味着收盘任务挂了，而不是市场休市。"""
    if perf.nav.days == 0:
        return [Finding(
            rule_id="nav_missing",
            subject=f"account{perf.account_id}",
            severity="P1",
            layer="execution",
            title=f"{perf.name} 没有任何净值记录",
            evidence=[f"sim_daily_nav 中 account_id={perf.account_id} 无数据"],
            why="没有净值曲线就算不出回撤和收益，复盘失去基准。",
            action="确认收盘任务是否在跑、DB 路径是否指向产机库。",
            data={},
        )]

    last = perf.nav.last_date or ""
    if not last or last >= as_of_iso:
        return []
    from datetime import date as _date

    try:
        gap = (_date.fromisoformat(as_of_iso) - _date.fromisoformat(last[:10])).days
    except ValueError:
        return []
    if gap < max_stale_days:
        return []
    return [Finding(
        rule_id="nav_stale",
        subject=f"account{perf.account_id}",
        severity="P1",
        layer="execution",
        title=f"{perf.name} 净值已 {gap} 天未更新",
        evidence=[f"最后一条净值 {last}，复盘日 {as_of_iso}"],
        why="收盘链路可能已经断了，后续所有绩效数字都在用过期快照。",
        action="检查 DailyClose / TradeJournal 任务与 DB 写入。",
        data={"last_nav_date": last, "gap_days": gap},
    )]


# ───────────────────────── 信号层规则 ─────────────────────────


def check_signal_quality(perf: Any, min_n: int = 5) -> list[Finding]:
    """某个信号持续亏钱时提出来，但只提假设，不直接判死刑。"""
    out: list[Finding] = []
    for row in perf.by_signal:
        n = row["n"]
        if n < min_n or row["net_pnl"] >= 0:
            continue
        est = row["expectancy"]
        out.append(Finding(
            rule_id="signal_negative_expectancy",
            subject=f"account{perf.account_id}.{row['signal']}",
            severity="P1" if n >= 20 else "P2",
            layer="signal",
            title=f"{perf.name} 信号「{row['signal']}」累计亏损 {abs(row['net_pnl']):,.0f} 元",
            evidence=[
                f"{n} 笔，胜率 {row['win_rate_pct']:.0f}%，单笔平均 {row['avg_pnl_pct']:+.2f}%",
                f"证据等级：{row['evidence']['label']}（{row['evidence']['can_do']}）",
                f"期望 95% 区间 [{est['ci_low_pct']}, {est['ci_high_pct']}]%"
                if est.get("ci_low_pct") is not None else "样本太少，无法给出期望区间",
            ],
            why="单一信号长期负期望，可能是入场条件不成立，也可能只是样本太小的运气。",
            action=("样本已够，可提改参提案并做影子对照。" if n >= 20
                    else f"继续观察，攒到 20 笔再判（还差 {20 - n} 笔）。"),
            data=row,
        ))
    return out


# ───────────────────────── 参数层规则 ─────────────────────────


def check_edge(perf: Any, min_n: int = 20) -> list[Finding]:
    """胜率够不够覆盖盈亏比。样本不足时只提示，不建议动手。"""
    if perf.closed_count < min_n or perf.breakeven_win_rate_pct is None:
        return []
    if perf.edge_gap_pct is None or perf.edge_gap_pct >= 0:
        return []
    return [Finding(
        rule_id="below_breakeven",
        subject=f"account{perf.account_id}",
        severity="P1",
        layer="parameter",
        title=f"{perf.name} 胜率低于保本线 {abs(perf.edge_gap_pct):.1f} 个点",
        evidence=[
            (f"实际胜率 {perf.win_rate_pct:.1f}%（{perf.win_count}/{perf.closed_count}），"
             f"95% 区间 [{perf.win_rate_ci[0] * 100:.1f}%, {perf.win_rate_ci[1] * 100:.1f}%]"),
            f"盈亏比 {perf.payoff_ratio:.2f} → 保本需要胜率 {perf.breakeven_win_rate_pct:.1f}%",
            f"证据等级：{perf.evidence['label']}（{perf.evidence['can_do']}）",
        ],
        why="在当前盈亏比下，这个胜率长期是负期望。要么提高胜率，要么放大盈亏比。",
        action="走参数层流程：先回测再影子验证，不要直接改生产参数。",
        data={
            "win_rate_pct": perf.win_rate_pct,
            "breakeven_pct": perf.breakeven_win_rate_pct,
            "payoff_ratio": perf.payoff_ratio,
        },
    )]


def check_drawdown(perf: Any, warn_pct: float = 10.0) -> list[Finding]:
    if perf.nav.max_drawdown_pct < warn_pct:
        return []
    return [Finding(
        rule_id="drawdown_breach",
        subject=f"account{perf.account_id}",
        severity="P1" if perf.nav.max_drawdown_pct >= warn_pct * 1.5 else "P2",
        layer="parameter",
        title=f"{perf.name} 最大回撤 {perf.nav.max_drawdown_pct:.1f}%",
        evidence=[
            f"当前回撤 {perf.nav.current_drawdown_pct:.1f}%，累计收益 {perf.nav.cumulative_return_pct:+.2f}%",
            f"最差单日 {perf.nav.worst_day_pct:+.2f}%，当前连亏 {perf.nav.losing_streak} 天",
        ],
        why="回撤超过风险预算时，先确认是止损没执行还是仓位过重，再谈参数。",
        action="核对止损是否按规则触发；确认后再评估是否收缩单笔预算。",
        data=perf.nav.to_dict(),
    )]


def run_all(
    specs: list[Any],
    performances: list[Any],
    funnels: dict[str, Any] | None = None,
    as_of_iso: str = "",
) -> list[Finding]:
    """跑全部规则。任一规则抛错都不该拖垮整份复盘。"""
    funnels = funnels or {}
    out: list[Finding] = []

    for spec in specs:
        for fn in (check_spec_health, check_capital_structure):
            out.extend(_safe(fn, spec))
        fu = funnels.get(spec.strategy_id)
        if fu is not None:
            out.extend(_safe(check_funnel, fu, spec))

    for perf in performances:
        out.extend(_safe(check_signal_quality, perf))
        out.extend(_safe(check_edge, perf))
        out.extend(_safe(check_drawdown, perf))
        if as_of_iso:
            out.extend(_safe(check_nav_freshness, perf, as_of_iso))

    return _sort(out)


def _safe(fn, *args) -> list[Finding]:
    try:
        return fn(*args) or []
    except Exception as exc:  # noqa: BLE001 - 单条规则失败不应中断复盘
        return [Finding(
            rule_id="rule_error",
            subject=fn.__name__,
            severity="P2",
            layer="execution",
            title=f"诊断规则 {fn.__name__} 执行失败",
            evidence=[f"{type(exc).__name__}: {exc}"],
            why="规则本身有 bug，对应的问题这次没被检查。",
            action="修 review/diagnostics.py 里该规则。",
        )]
