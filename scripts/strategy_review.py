"""scripts/strategy_review.py — 每日策略复盘，交易反馈闭环的入口。

和已有的 daily_review / daily_close_report 分工：
  trade_journal      记录今天成交了什么（事实）
  daily_close_report 播报今天赚了多少（结果）
  strategy_review    判断策略本身哪里不对、今天该改什么（诊断）  ← 本文件

产物：
  output/strategy_review/YYYY-MM-DD.md    人读的复盘
  output/strategy_review/YYYY-MM-DD.json  机器读的结构化结论
  docs/STRATEGY_SPEC.md                   当前策略说明书（--write-spec）
  pm/strategy_review/hypotheses.json      假设台账
  pm/strategy_review/spec_snapshots.json  参数快照（漂移检测基准）

常用：
  python scripts/strategy_review.py --no-push              # 本地看一眼
  python scripts/strategy_review.py --write-spec           # 顺手刷新策略说明书
  python scripts/strategy_review.py --open-hypothesis --param swing.max_positions \\
      --before 3 --after 5 --expect "满仓拦截归零，月成交回到 8 笔以上"
  python scripts/strategy_review.py --close-hypothesis H-001 --status confirmed --outcome "..."
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Windows 产机控制台是 GBK，中文报告会直接抛 UnicodeEncodeError
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from review import diagnostics  # noqa: E402
from review import ledger as ledger_mod
from review.funnel import build_swing_funnel  # noqa: E402
from review.metrics import analyze_account  # noqa: E402
from review.spec import load_specs  # noqa: E402
from review.spec import render_markdown as render_spec_markdown

LAYER_ORDER = ["execution", "signal", "parameter"]


def resolve_db(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    try:
        from sim.config_resolver import resolve_db_path

        return resolve_db_path()
    except Exception:
        return ROOT / "data" / "sim_live_mirror.db"


def artifact_dir() -> Path:
    try:
        from sim.config_resolver import resolve_artifact_root

        base = resolve_artifact_root()
    except Exception:
        base = ROOT / "output"
    d = Path(base) / "strategy_review"
    d.mkdir(parents=True, exist_ok=True)
    return d


def collect(day: str, db_path: Path, lookback: int, ledger_dir: Path | None = None) -> dict:
    """跑完整条复盘链，返回结构化结果。"""
    as_of = date.fromisoformat(day)
    specs = load_specs()

    performances = [analyze_account(db_path, s.account_id, s.name, as_of=as_of) for s in specs]

    funnels = {}
    swing = next((s for s in specs if s.strategy_id == "swing"), None)
    if swing is not None:
        funnels["swing"] = build_swing_funnel(
            root=ROOT,
            as_of=as_of,
            lookback=lookback,
            max_positions=swing.value("max_positions"),
            single_budget=swing.value("single_budget"),
            initial_cash=swing.value("initial_cash"),
        )

    led = ledger_mod.Ledger(ledger_dir)
    state = led.build_state(specs, day)

    findings = diagnostics.run_all(specs, performances, funnels, as_of_iso=day)
    findings.extend(ledger_mod.check_ledger(state, day))
    findings = sorted(findings, key=lambda f: (diagnostics.SEVERITY_ORDER.get(f.severity, 9),
                                               LAYER_ORDER.index(f.layer) if f.layer in LAYER_ORDER else 9,
                                               f.rule_id))

    return {
        "date": day,
        "db_path": str(db_path),
        "specs": specs,
        "performances": performances,
        "funnels": funnels,
        "ledger": state,
        "findings": findings,
    }


def to_json(result: dict) -> dict:
    return {
        "date": result["date"],
        "db_path": result["db_path"],
        "specs": [s.to_dict() for s in result["specs"]],
        "performances": [p.to_dict() for p in result["performances"]],
        "funnels": {k: v.to_dict() for k, v in result["funnels"].items()},
        "ledger": result["ledger"].to_dict(),
        "findings": [f.to_dict() for f in result["findings"]],
        "summary": summarize(result),
    }


def summarize(result: dict) -> dict:
    findings = result["findings"]
    by_sev = {s: sum(1 for f in findings if f.severity == s) for s in ("P0", "P1", "P2")}
    by_layer = {ly: sum(1 for f in findings if f.layer == ly) for ly in LAYER_ORDER}
    actionable = [f for f in findings if f.layer == "execution"]
    return {
        "findings_total": len(findings),
        "by_severity": by_sev,
        "by_layer": by_layer,
        "actionable_today": len(actionable),
        "open_hypotheses": len(result["ledger"].open_items()),
        "due_hypotheses": len(result["ledger"].due_items(result["date"])),
        "headline": headline(result),
    }


def headline(result: dict) -> str:
    findings = result["findings"]
    p0 = [f for f in findings if f.severity == "P0"]
    if p0:
        return f"{len(p0)} 个 P0 待修，最紧要：{p0[0].title}"
    p1 = [f for f in findings if f.severity == "P1"]
    if p1:
        return f"无 P0；{len(p1)} 个 P1 待处理，最紧要：{p1[0].title}"
    return "今日无 P0/P1，策略按既定规则运行"


# ─────────────────────────── 渲染 ───────────────────────────


def render_markdown(result: dict) -> str:
    day = result["date"]
    s = summarize(result)
    lines = [
        f"# 策略复盘 {day}",
        "",
        f"> {s['headline']}",
        (f"> 发现 {s['findings_total']} 项（P0 {s['by_severity']['P0']} / P1 {s['by_severity']['P1']} "
         f"/ P2 {s['by_severity']['P2']}），其中 **{s['actionable_today']} 项今天就能改**。"),
        "",
        "## 当前跑的是什么策略",
        "",
    ]
    for spec in result["specs"]:
        lines.append(f"- **{spec.name}** `{spec.spec_hash()}` — {spec.headline}")
    lines += ["", "> 完整参数见 [docs/STRATEGY_SPEC.md](../../docs/STRATEGY_SPEC.md)（自动生成）。", ""]

    lines += _render_findings(result["findings"])
    lines += _render_performance(result["performances"])
    lines += _render_funnel(result["funnels"])
    lines += _render_ledger(result["ledger"], day)

    lines += [
        "## 怎么用这份报告",
        "",
        "1. **执行层**的问题今天就动手 —— 那是 bug 或算术矛盾，不需要等样本。",
        ("2. **信号层 / 参数层**的问题只登记假设，攒够样本再动。方法论见 "
         "[docs/METHODOLOGY.md](../../docs/METHODOLOGY.md)。"),
        "3. 改任何参数之前先开假设，否则明天这里会报「无记录的参数变更」。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _render_findings(findings: list) -> list[str]:
    if not findings:
        return ["## 今日发现", "", "无。链路正常，指标未触发任何规则。", ""]

    lines = ["## 今日发现", ""]
    for layer in LAYER_ORDER:
        group = [f for f in findings if f.layer == layer]
        if not group:
            continue
        label = diagnostics.LAYER_LABEL.get(layer, layer)
        horizon = diagnostics.LAYER_HORIZON.get(layer, "")
        lines += [f"### {label}（{horizon}）", ""]
        for f in group:
            lines.append(f"#### `{f.severity}` {f.title}")
            lines.append("")
            for e in f.evidence:
                lines.append(f"- {e}")
            lines += ["", f"**为什么是问题**：{f.why}", "", f"**建议动作**：{f.action}", ""]
    return lines


def _render_performance(performances: list) -> list[str]:
    lines = ["## 绩效与可信度", "",
             "| 账户 | 已平仓 | 胜率(95%区间) | 盈亏比 | 保本胜率 | 净盈亏 | 累计 | 最大回撤 | 证据等级 |",
             "|------|-------:|--------------|-------:|---------:|-------:|-----:|---------:|----------|"]
    for p in performances:
        if p.closed_count:
            wr = (f"{p.win_rate_pct:.0f}% "
                  f"[{p.win_rate_ci[0] * 100:.0f},{p.win_rate_ci[1] * 100:.0f}]")
        else:
            wr = "—"
        payoff = f"{p.payoff_ratio:.2f}" if p.payoff_ratio else "—"
        be = f"{p.breakeven_win_rate_pct:.0f}%" if p.breakeven_win_rate_pct is not None else "—"
        lines.append(
            f"| {p.name} | {p.closed_count} | {wr} | {payoff} | {be} | "
            f"{p.net_pnl:+,.0f} | {p.nav.cumulative_return_pct:+.2f}% | "
            f"{p.nav.max_drawdown_pct:.2f}% | {p.evidence['label']} |"
        )
    lines.append("")

    weak = [p for p in performances if p.evidence["level"] in ("none", "anecdote", "weak")]
    if weak:
        names = "、".join(p.name for p in weak)
        lines += [
            f"> {names} 的样本量还撑不起统计结论（{'; '.join(p.evidence['can_do'] for p in weak[:1])}）。",
            "> 这些账户的胜率数字**不要用来改参数**。",
            "",
        ]

    for p in performances:
        if p.samples_to_prove:
            lines.append(f"> {p.name}：按当前胜率，还要 **{p.samples_to_prove} 笔**已平仓才能证明"
                         f"优势不是运气（现有 {p.closed_count} 笔）。")
    if any(p.samples_to_prove for p in performances):
        lines.append("")

    for p in performances:
        if not p.by_signal:
            continue
        lines += [f"### {p.name} 按信号归因", "", "| 信号 | 笔数 | 胜率 | 净盈亏 | 单笔均值 | 证据 |",
                  "|------|-----:|-----:|-------:|---------:|------|"]
        for row in p.by_signal:
            lines.append(f"| {row['signal']} | {row['n']} | {row['win_rate_pct']:.0f}% | "
                         f"{row['net_pnl']:+,.0f} | {row['avg_pnl_pct']:+.2f}% | {row['evidence']['label']} |")
        lines.append("")
    return lines


def _render_funnel(funnels: dict) -> list[str]:
    if not funnels:
        return []
    lines = ["## 信号漏斗", ""]
    for name, fu in funnels.items():
        if not fu.days:
            lines += [f"### {name}", "", "无漏斗数据。", ""]
            continue
        lines += [
            f"### {name}（近 {len(fu.days)} 个交易日）",
            "",
            f"- 累计成交 **{fu.total_fills}** 笔，其中 {fu.days_with_advice} 天有买点建议",
            f"- 连续 0 成交 **{fu.zero_fill_streak}** 天；出了买点却没成交 **{fu.advice_not_filled_days}** 天"
            f"（按当前仓位上限仍会被满仓挡住的：{fu.blocked_days} 天）",
        ]
        if fu.capital_cap_pct is not None:
            lines.append(f"- 资金利用率上限 **{fu.capital_cap_pct:.0f}%**"
                         + (f"，当前闲置现金 {fu.idle_cash_pct:.0f}%" if fu.idle_cash_pct is not None else ""))
        lines += ["", "| 日期 | 宽基 | 过硬过滤 | 过分线 | 入池 | 买点 | 成交 | 持仓 | 备注 |",
                  "|------|-----:|--------:|------:|-----:|-----:|-----:|-----:|------|"]
        for d in fu.days:
            g = {st.key: st.count for st in d.stages}
            note = []
            if d.blocked_by_position_cap:
                note.append("满仓拦截")
            if d.pool_fallback:
                note.append("池子兜底")
            if d.legacy_schema:
                note.append("旧版埋点")
            lines.append(
                f"| {d.day} | {_n(g.get('universe'))} | {_n(g.get('candidates'))} | "
                f"{_n(g.get('above_min_score'))} | {_n(g.get('pool'))} | {_n(d.advice)} | "
                f"{_n(d.fills)} | {_n(d.positions)} | {'/'.join(note) or '—'} |"
            )
        lines.append("")
    return lines


def _render_ledger(state, day: str) -> list[str]:
    lines = ["## 假设台账", ""]
    open_items = state.open_items()
    if not open_items:
        lines += ["当前没有在验证的假设。", "",
                  "> 这不是好事：说明最近的改动都没有立预期，改完也无从判断有没有用。", ""]
    else:
        lines += ["| ID | 假设 | 参数 | 立于 | 复核日 | 状态 |", "|----|------|------|------|--------|------|"]
        for h in open_items:
            due = "**到期**" if h.is_due(day) else h.review_after
            lines.append(f"| {h.id} | {h.title} | `{h.param or '—'}` | {h.created} | {due} | {h.status} |")
        lines.append("")

    closed = [h for h in state.hypotheses if h.status != ledger_mod.STATUS_OPEN]
    if closed:
        lines += ["### 已结案（这些是攒下来的方法论）", ""]
        for h in closed[-10:]:
            lines.append(f"- `{h.status}` **{h.title}** — {h.outcome or '无结论记录'}")
        lines.append("")
    return lines


def _n(v) -> str:
    return "—" if v is None else str(v)


def _write(path: Path, text: str) -> None:
    """统一 LF 落盘，保证产机（Windows）与开发机产出逐字节一致。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def render_wecom(result: dict) -> str:
    """企微只放判断和动作，明细留在报告里。"""
    s = summarize(result)
    day = result["date"]
    lines = [f"**策略复盘 {day}**", f"> {s['headline']}", ""]

    today_items = [f for f in result["findings"] if f.layer == "execution"][:4]
    if today_items:
        lines.append("**今天能改的：**")
        for f in today_items:
            lines.append(f"- `{f.severity}` {f.title}")
    else:
        lines.append("执行层无待修项。")

    lines.append("")
    for p in result["performances"]:
        if p.closed_count:
            lines.append(f"{p.name}：{p.closed_count} 笔平仓，胜率 {p.win_rate_pct:.0f}%"
                         f"（{p.evidence['label']}），累计 {p.nav.cumulative_return_pct:+.2f}%")
        else:
            lines.append(f"{p.name}：无已平仓样本，累计 {p.nav.cumulative_return_pct:+.2f}%")

    if s["due_hypotheses"]:
        lines += ["", f"⏰ {s['due_hypotheses']} 条假设到期待核对"]
    lines += ["", f"明细：output/strategy_review/{day}.md"]
    return "\n".join(lines)


# ─────────────────────────── CLI ───────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="每日策略复盘与自我改进闭环")
    ap.add_argument("--date", default=date.today().isoformat(), help="复盘日期 YYYY-MM-DD")
    ap.add_argument("--db", default=None, help="SQLite 路径，默认走 config_resolver")
    ap.add_argument("--lookback", type=int, default=15, help="漏斗回看交易日数")
    ap.add_argument("--ledger-dir", default=None, help="假设台账目录（测试用）")
    ap.add_argument("--out-dir", default=None, help="报告输出目录")
    ap.add_argument("--write-spec", action="store_true", help="同时刷新 docs/STRATEGY_SPEC.md")
    ap.add_argument("--push", dest="push", action="store_true", default=None, help="推送企微")
    ap.add_argument("--no-push", dest="push", action="store_false", help="不推送")
    ap.add_argument("--json", action="store_true", help="stdout 打印 JSON")
    ap.add_argument("--quiet", action="store_true", help="不打印报告正文")

    ap.add_argument("--open-hypothesis", action="store_true", help="登记一条假设后退出")
    ap.add_argument("--param", default="", help="假设涉及的参数，如 swing.max_positions")
    ap.add_argument("--before", default=None, help="改动前的值")
    ap.add_argument("--after", default=None, help="改动后的值")
    ap.add_argument("--expect", default="", help="预期什么指标怎么变")
    ap.add_argument("--metric", default="", help="用哪个指标验证")
    ap.add_argument("--title", default="", help="假设标题，缺省用 param+expect 拼")
    ap.add_argument("--layer", default="parameter", choices=LAYER_ORDER, help="改动层级")
    ap.add_argument("--horizon-days", type=int, default=21, help="多少天后复核")
    ap.add_argument("--min-samples", type=int, default=20, help="至少要几笔样本才算数")

    ap.add_argument("--close-hypothesis", default="", help="结案的假设 ID")
    ap.add_argument("--status", default="", choices=["", "confirmed", "rejected", "inconclusive", "abandoned"])
    ap.add_argument("--outcome", default="", help="结案结论")

    args = ap.parse_args(argv)
    ledger_dir = Path(args.ledger_dir) if args.ledger_dir else None
    led = ledger_mod.Ledger(ledger_dir)

    if args.open_hypothesis:
        if not args.expect:
            print("需要 --expect：写不出预期的改动不值得做", file=sys.stderr)
            return 2
        title = args.title or (f"{args.param}: {args.expect}" if args.param else args.expect)
        h = led.open_hypothesis(
            title=title, layer=args.layer, today=args.date, param=args.param,
            before=args.before, after=args.after, expect=args.expect, metric=args.metric,
            horizon_days=args.horizon_days, min_samples=args.min_samples,
        )
        print(f"已登记 {h.id}：{h.title}")
        print(f"  复核日 {h.review_after}，最少 {h.min_samples} 笔样本")
        return 0

    if args.close_hypothesis:
        if not args.status:
            print("需要 --status", file=sys.stderr)
            return 2
        h = led.close_hypothesis(args.close_hypothesis, args.status, args.outcome, args.date)
        if h is None:
            print(f"找不到假设 {args.close_hypothesis}", file=sys.stderr)
            return 1
        print(f"{h.id} 已结案：{h.status} — {h.outcome}")
        return 0

    db_path = resolve_db(args.db)
    result = collect(args.date, db_path, args.lookback, ledger_dir)

    md = render_markdown(result)
    payload = to_json(result)

    out_dir = Path(args.out_dir) if args.out_dir else artifact_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    # 固定 LF：产机是 Windows，text 模式默认写 CRLF，和开发机交替跑会让
    # 每份产物每天整文件 diff 一次，真正改了哪个参数反而看不出来。
    _write(out_dir / f"{args.date}.md", md)
    _write(out_dir / f"{args.date}.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    if args.write_spec:
        spec_doc = ROOT / "docs" / "STRATEGY_SPEC.md"
        _write(spec_doc, render_spec_markdown(result["specs"]))
        print(f"已刷新 {spec_doc.relative_to(ROOT)}")

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif not args.quiet:
        print(md)

    print(f"已写出 {out_dir / (args.date + '.md')}")

    should_push = args.push
    if should_push is None:
        should_push = bool(os.environ.get("WECOM_WEBHOOK"))
    if should_push:
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from wecom_webhook import push_markdown_safe

            push_markdown_safe(render_wecom(result))
        except Exception as exc:  # noqa: BLE001 - 推送失败不该让复盘失败
            print(f"企微推送失败（报告已落盘）：{exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
