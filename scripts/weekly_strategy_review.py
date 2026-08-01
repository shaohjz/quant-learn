"""scripts/weekly_strategy_review.py — 每周策略复盘（把研究链接上生产）

研究脚本（回测 / 影子对照 / 晋级证据）本来就写得不错，问题是**没挂调度、
也没有落地出口**：跑完产出一堆 JSON，要人记得去看、看懂、再手改代码。
2026-07-31 那轮就是这么跑的一次性动作。

本脚本把它串成每周自动执行的一条链：

    optimize 回测 → shadow 只读对照 → 晋级证据 → 参数提案 → 护栏 → 采纳或开单

产出：
  output/strategy_research/proposal.json     机器可执行的参数提案
  pm/strategy_review/YYYY-MM-DD-review.md    人读的复盘与建议

三道**独立于 PromotionGate** 的红线（门禁只回答统计证据，不回答数据质量）：

1. `audit.research_only=true`（CSV 缺 raw/复权元数据）→ 绝不自动采纳
2. 参数护栏（边界/限幅/冷却/白名单）→ research/param_guard.py
3. 观察窗内退化 → 自动回滚上一次采纳

用法：
  python scripts/weekly_strategy_review.py --skip-backtest   # 用已有 JSON 快速走一遍
  python scripts/weekly_strategy_review.py --dry-run
  python scripts/weekly_strategy_review.py
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from apply_strategy_params import current_effective, do_apply, do_rollback, read_audit  # noqa: E402
from research.param_guard import GuardConfig, should_rollback  # noqa: E402
from sim.config_resolver import resolve_artifact_root  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("weekly_review")

# 研究脚本的候选参数名 → 生产配置点路径。
# 只映射 #3 波段：#1 的阈值由 daily_recalibrate 按 MA/ATR 每日重算，
# 不适合用周度回测的静态值去覆盖。
ACCOUNT3_PARAM_MAP = {
    "a_ma20_tolerance": "swing_strategy.signals.a_ma20_tolerance",
    "b_ma10_tolerance": "swing_strategy.signals.b_ma10_tolerance",
    "max_volume_ratio": "swing_strategy.signals.max_volume_ratio",
    "min_expected_rr": "swing_strategy.filters.min_net_rr",
    "min_score": "swing_strategy.execution.min_score_buy",
}


def _research_dir() -> Path:
    d = resolve_artifact_root() / "strategy_research"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def run_research_chain(as_of: str, timeout: int = 3600) -> dict:
    """依次跑三个研究脚本。任一步失败只记录，不阻断后面的提案生成。"""
    py = sys.executable
    data_dir = str(ROOT / "data")
    research = _research_dir()
    promotion = resolve_artifact_root() / "promotion"

    steps = [
        (
            "optimize",
            [py, str(ROOT / "scripts" / "run_dual_strategy_backtest.py"), data_dir,
             "--mode", "optimize", "--start", "2024-07-01", "--end", "2026-05-20",
             "--holdout", "2026-02-01", "--allow-adjusted-research",
             "--output", str(research / "optimize.json")],
        ),
        (
            "shadow",
            [py, str(ROOT / "scripts" / "compare_strategy_shadow.py"), data_dir,
             "--start", "2025-01-01", "--end", "2026-05-20",
             "--optimize-json", str(research / "optimize.json"),
             "--allow-adjusted-research", "--output", str(research / "shadow.json")],
        ),
        (
            "evidence",
            [py, str(ROOT / "scripts" / "weekly_strategy_evidence.py"),
             "--optimization-report", str(research / "optimize.json"),
             "--output", str(promotion)],
        ),
    ]

    results: dict[str, Any] = {}
    for name, cmd in steps:
        log.info("跑 %s ...", name)
        try:
            proc = subprocess.run(
                cmd, cwd=str(ROOT), capture_output=True, text=True,
                timeout=timeout, encoding="utf-8", errors="replace",
            )
            results[name] = {"returncode": proc.returncode, "tail": (proc.stderr or proc.stdout or "")[-500:]}
            if proc.returncode != 0:
                log.warning("%s 退出码 %s", name, proc.returncode)
        except (subprocess.TimeoutExpired, OSError) as exc:
            results[name] = {"returncode": -1, "tail": str(exc)}
            log.warning("%s 执行失败：%s", name, exc)
    return results


def read_gate(as_of: str) -> dict:
    """读晋级门禁结论。找不到当日文件就退回最近一份。"""
    promo_dir = resolve_artifact_root() / "promotion"
    path = promo_dir / f"{as_of}.json"
    if not path.exists():
        candidates = sorted(promo_dir.glob("*.json")) if promo_dir.exists() else []
        if not candidates:
            return {}
        path = candidates[-1]
    data = _read_json(path)
    data["_source"] = str(path)
    return data


def gate_verdict(gate: dict, account_id: int = 3) -> tuple[bool, str]:
    """PromotionGate 对某账户是否放行。结构缺失一律当作不通过。"""
    acct = ((gate.get("accounts") or {}).get(str(account_id))) or {}
    if not acct:
        return False, "晋级报告里没有该账户的结论"

    strategies = acct.get("strategies") or []
    passed = [s for s in strategies if (s.get("promotion") or {}).get("can_promote")]
    if passed:
        names = ", ".join(str(s.get("strategy")) for s in passed)
        return True, f"门禁放行：{names}"

    blockers: list[str] = []
    for s in strategies:
        promo = s.get("promotion") or {}
        for reason in (promo.get("blockers") or promo.get("reasons") or []):
            blockers.append(str(reason))
    return False, ("；".join(blockers[:3]) if blockers else "门禁未给出放行结论")


def build_proposal(optimize: dict, current: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """候选参数 → 提案。只保留与当前值不同的键。"""
    best = ((optimize.get("accounts") or {}).get("account3") or {}).get("final_best_params") or {}
    notes: list[str] = []
    proposal: dict[str, Any] = {}
    for name, value in best.items():
        key = ACCOUNT3_PARAM_MAP.get(name)
        if not key:
            notes.append(f"候选参数 `{name}` 没有对应的生产配置键，跳过")
            continue
        if current.get(key) == value:
            continue
        proposal[key] = value
    return proposal, notes


def research_only(optimize: dict) -> bool:
    return bool((optimize.get("audit") or {}).get("research_only"))


def check_rollback(as_of: str, guard_cfg: dict) -> tuple[bool, str]:
    """观察窗内看记分卡是否退化。没有采纳记录或未到观察期则不动。"""
    rb = ((guard_cfg.get("auto_apply") or {}).get("rollback")) or {}
    if not rb.get("enabled", True):
        return False, "回滚检查已关闭"

    applied = [r for r in read_audit() if r.get("action") == "apply"]
    if not applied:
        return False, "没有自动采纳记录"

    last = applied[-1]
    try:
        elapsed = (date.fromisoformat(as_of) - date.fromisoformat(last["date"])).days
    except (ValueError, KeyError):
        return False, "采纳记录日期异常"
    if elapsed < int(rb.get("watch_days", 10)):
        return False, f"采纳于 {last['date']}，观察期未满"

    card = _read_json(resolve_artifact_root() / "strategy_scorecard" / "latest.json")
    windows = card.get("windows") or {}
    if not windows:
        return False, "没有记分卡，无法判断退化"
    longest = max(windows, key=lambda k: int(str(k).rstrip("d")))
    current_exp = (windows[longest].get("overall") or {}).get("mean_fwd_5d")
    baseline = last.get("baseline_expectancy")

    should, reason = should_rollback(baseline, current_exp, float(rb.get("degrade_pct", 0.5)))
    return should, reason


def write_review(as_of: str, payload: dict) -> Path:
    out_dir = ROOT / "pm" / "strategy_review"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{as_of}-review.md"

    gate_ok = payload["gate_passed"]
    proposal = payload["proposal"]
    lines = [
        f"# 每周策略复盘 — {as_of}",
        "",
        f"> 自动生成。研究链只读，采纳受 `strategy_feedback.auto_apply` 护栏控制。",
        "",
        "## 结论",
        "",
        f"- 晋级门禁：**{'通过' if gate_ok else '未通过'}** — {payload['gate_reason']}",
        f"- 数据质量：{'⚠️ research_only（CSV 缺 raw 元数据），本轮禁止自动采纳' if payload['research_only'] else '可用于生产判断'}",
        f"- 参数提案：{len(proposal)} 项" + ("（无差异，维持现状）" if not proposal else ""),
        f"- 自动采纳：{payload['apply_summary']}",
        f"- 回滚检查：{payload['rollback_reason']}",
        "",
    ]

    if proposal:
        lines += [
            "## 提案明细",
            "",
            "| 参数 | 当前 | 候选 |",
            "|------|-----:|-----:|",
        ]
        for key, val in sorted(proposal.items()):
            lines.append(f"| `{key}` | {payload['current'].get(key)} | {val} |")
        lines.append("")

    if payload.get("notes"):
        lines += ["## 备注", ""] + [f"- {n}" for n in payload["notes"]] + [""]

    if payload.get("chain"):
        lines += ["## 研究链执行", "", "| 步骤 | 退出码 |", "|------|-------:|"]
        for name, res in payload["chain"].items():
            lines.append(f"| {name} | {res['returncode']} |")
        lines.append("")

    lines += [
        "## 人工采纳（护栏关闭时用）",
        "",
        "```bat",
        ".venv\\Scripts\\python.exe -u scripts\\apply_strategy_params.py ^",
        "  --proposal output\\strategy_research\\proposal.json --gate-passed --dry-run",
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="每周策略复盘：研究链 → 提案 → 护栏采纳")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--skip-backtest", action="store_true", help="复用已有 JSON，不重跑研究链")
    ap.add_argument("--dry-run", action="store_true", help="不写参数、不回滚")
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()

    try:
        from sim.config import load_config

        cfg = load_config()
    except Exception:
        cfg = {}
    feedback_cfg = cfg.get("strategy_feedback") or {}

    chain = {} if args.skip_backtest else run_research_chain(args.date, args.timeout)

    optimize = _read_json(_research_dir() / "optimize.json")
    gate = read_gate(args.date)
    gate_ok, gate_reason = gate_verdict(gate)
    is_research_only = research_only(optimize)

    current = current_effective()
    proposal, notes = build_proposal(optimize, current)
    if gate.get("_source"):
        notes.append(f"晋级报告来源：{gate['_source']}")

    (_research_dir() / "proposal.json").write_text(
        json.dumps(
            {
                "as_of": args.date,
                "gate_passed": gate_ok,
                "gate_reason": gate_reason,
                "research_only": is_research_only,
                "current": {k: current.get(k) for k in proposal},
                "params": proposal,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # research_only 数据永远不许自动改生产参数，哪怕门禁放行。
    effective_gate = gate_ok and not is_research_only
    if is_research_only and gate_ok:
        notes.append("门禁虽放行，但输入数据标记 research_only，已强制阻断自动采纳")

    apply_summary = "无提案，未调用采纳"
    if proposal:
        guard = GuardConfig.from_config(cfg)
        if not guard.enabled:
            apply_summary = "auto_apply.enabled=false，只出提案不写参数"
        do_apply(proposal, effective_gate, args.date, args.dry_run or not guard.enabled)
        if guard.enabled:
            apply_summary = "已调用采纳（结果见 pm/strategy_review/*-param-apply.md）"

    should_rb, rb_reason = check_rollback(args.date, feedback_cfg)
    if should_rb and not args.dry_run:
        log.warning("触发回滚：%s", rb_reason)
        do_rollback(args.date, dry_run=False)

    report = write_review(
        args.date,
        {
            "gate_passed": gate_ok,
            "gate_reason": gate_reason,
            "research_only": is_research_only,
            "proposal": proposal,
            "current": current,
            "notes": notes,
            "chain": chain,
            "apply_summary": apply_summary,
            "rollback_reason": rb_reason,
        },
    )
    log.info("复盘报告：%s", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
