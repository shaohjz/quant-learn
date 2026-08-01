"""scripts/apply_strategy_params.py — 受护栏保护的策略参数写入器

唯一被允许自动改生产参数的入口。所有检查在 research/param_guard.py，
本脚本负责真正落盘、备份、审计、留痕、回滚。

安全设计：

- **只写 `config.strategy_params.yaml`** 这一个小文件，永不碰 42KB 的 `config.yaml`。
  好处是 diff 一眼看得完、回滚只需恢复一个文件、也不会把人写的注释洗掉。
- **每次写入前备份**到 `output/strategy_params/backup/`，审计流水记录 before/after。
- **写入即在假设记账里开一条**（review/ledger.py）。没有假设的参数改动会被
  复盘系统判为 P0「静默改参」——自动改参也必须留下可证伪的预期，否则
  和随机游走没区别。
- 出问题回滚：`--rollback`，从最近一条审计记录还原 before 值。

默认 `strategy_feedback.auto_apply.enabled=false`，此脚本会拒绝一切写入，
只打印判定结果。样本量够了再在 config.yaml 里打开。

用法：
  python scripts/apply_strategy_params.py --proposal output/strategy_research/proposal.json --dry-run
  python scripts/apply_strategy_params.py --proposal ... --gate-passed
  python scripts/apply_strategy_params.py --rollback
  python scripts/apply_strategy_params.py --show
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

from quant_core.swing_params import AUTO_PARAMS_FILE, load_auto_overrides, resolve_params_dict  # noqa: E402
from research.param_guard import GuardConfig, evaluate_proposal  # noqa: E402
from sim.config_resolver import resolve_artifact_root  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("apply_params")

PARAM_ROOT = "swing_strategy"


def _store_dir() -> Path:
    d = resolve_artifact_root() / "strategy_params"
    d.mkdir(parents=True, exist_ok=True)
    return d


def audit_path() -> Path:
    return _store_dir() / "audit.jsonl"


def flatten(tree: dict, prefix: str = PARAM_ROOT) -> dict[str, Any]:
    """参数树 → 点路径扁平 dict。列表等非标量原样保留，由护栏拒绝。"""
    out: dict[str, Any] = {}
    for key, val in (tree or {}).items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(val, dict):
            out.update(flatten(val, path))
        else:
            out[path] = val
    return out


def unflatten(flat: dict[str, Any], strip_prefix: str = PARAM_ROOT) -> dict:
    """点路径扁平 dict → 嵌套树，并去掉根前缀（写进 yaml 的 swing_strategy 下）。"""
    out: dict = {}
    for path, val in flat.items():
        parts = path.split(".")
        if strip_prefix and parts and parts[0] == strip_prefix:
            parts = parts[1:]
        if not parts:
            continue
        node = out
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = val
    return out


def current_effective() -> dict[str, Any]:
    """当前生效参数（defaults + config.yaml + 已有自动层）的扁平视图。"""
    try:
        from sim.config import load_config

        cfg = load_config()
    except Exception:
        cfg = {}
    merged, _ = resolve_params_dict(cfg)
    return flatten(merged)


def read_audit() -> list[dict]:
    path = audit_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def last_applied_date(records: list[dict] | None = None) -> str | None:
    records = read_audit() if records is None else records
    applied = [r for r in records if r.get("action") == "apply"]
    return applied[-1]["date"] if applied else None


def append_audit(record: dict) -> None:
    with audit_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def backup_current() -> str | None:
    """备份现有自动层文件，返回备份路径。文件不存在（首次采纳）时返回 None。"""
    if not AUTO_PARAMS_FILE.exists():
        return None
    backup_dir = _store_dir() / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"config.strategy_params.{stamp}.yaml"
    shutil.copy2(AUTO_PARAMS_FILE, dest)
    return str(dest)


def write_auto_layer(changes: dict[str, Any], meta: dict) -> None:
    """把改动并进自动覆盖层。只动 changes 里的键，其余保留。"""
    existing = load_auto_overrides()
    merged_flat = flatten({PARAM_ROOT: existing} if existing else {})
    merged_flat.update(changes)
    payload = {
        "# 说明": "本文件由 scripts/apply_strategy_params.py 自动维护，不要手改；"
                  "人工调参请写 config.yaml 的 swing_strategy 段",
        "meta": meta,
        PARAM_ROOT: unflatten(merged_flat),
    }
    AUTO_PARAMS_FILE.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def open_hypothesis(changes: dict[str, Any], current: dict[str, Any], today: str) -> str:
    """在假设记账里立赌约。review 包缺失时降级为空，不阻断写入。"""
    try:
        from review.ledger import Ledger
    except Exception as exc:
        log.warning("假设记账不可用（%s），本次改参没有留下可证伪预期", exc)
        return ""

    keys = ", ".join(sorted(changes))
    try:
        ledger = Ledger()
        h = ledger.open_hypothesis(
            title=f"自动采纳参数：{keys}",
            layer="parameter",
            today=today,
            param=next(iter(sorted(changes))),
            before={k: current.get(k) for k in changes},
            after=dict(changes),
            expect="采纳后 5 日前瞻净期望不低于采纳前基线的 50%，否则回滚",
            metric="signal_outcomes.mean_fwd_5d",
            source_finding="scripts/weekly_strategy_review.py",
        )
        return h.id
    except Exception as exc:
        log.warning("写假设记账失败：%s", exc)
        return ""


def write_report(record: dict) -> Path:
    """人读的采纳说明，落在 pm/strategy_review/（DailyGitSync 白名单内）。"""
    out_dir = ROOT / "pm" / "strategy_review"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{record['date']}-param-apply.md"

    lines = [
        f"# 策略参数自动采纳 — {record['date']}",
        "",
        f"- 判定：**{'已采纳' if record['action'] == 'apply' else '未采纳'}**",
        f"- 原因：{record['reason']}",
        f"- PromotionGate：{'通过' if record.get('gate_passed') else '未通过'}",
        f"- 假设编号：{record.get('hypothesis_id') or '（无）'}",
        f"- 备份：{record.get('backup') or '（首次采纳，无历史文件）'}",
        "",
        "## 逐项判定",
        "",
        "| 参数 | 当前 | 提案 | 实际写入 | 结果 | 说明 |",
        "|------|-----:|-----:|--------:|:----:|------|",
    ]
    for v in record.get("verdicts", []):
        lines.append(
            f"| `{v['key']}` | {v['current']} | {v['proposed']} | "
            f"{v['applied'] if v['applied'] is not None else '—'} | {v['status']} | {v['reason']} |"
        )
    lines += [
        "",
        "## 回滚",
        "",
        "```bat",
        ".venv\\Scripts\\python.exe -u scripts\\apply_strategy_params.py --rollback",
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def do_apply(proposal: dict[str, Any], gate_passed: bool, as_of: str, dry_run: bool) -> int:
    try:
        from sim.config import load_config

        cfg = load_config()
    except Exception:
        cfg = {}

    guard = GuardConfig.from_config(cfg)
    current = current_effective()
    decision = evaluate_proposal(
        current, proposal, guard, gate_passed, as_of, last_applied_date()
    )

    log.info("护栏判定：%s（%s）", "放行" if decision.allowed else "拦截", decision.reason)
    for v in decision.verdicts:
        log.info("  %s: %s → %s [%s] %s", v.key, v.current, v.proposed, v.status, v.reason)

    record = {
        "date": as_of,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": "apply" if (decision.allowed and not dry_run) else "skip",
        "reason": decision.reason,
        "gate_passed": gate_passed,
        "changes": decision.changes,
        "before": {k: current.get(k) for k in decision.changes},
        "verdicts": [v.to_dict() for v in decision.verdicts],
    }

    if not decision.allowed:
        append_audit(record)
        write_report(record)
        return 0
    if dry_run:
        log.info("dry-run：不写入。将会改动 %s", decision.changes)
        return 0

    record["backup"] = backup_current()
    record["hypothesis_id"] = open_hypothesis(decision.changes, current, as_of)
    write_auto_layer(
        decision.changes,
        {
            "applied_at": record["timestamp"],
            "reason": decision.reason,
            "hypothesis_id": record["hypothesis_id"],
            "gate_passed": gate_passed,
        },
    )
    append_audit(record)
    report = write_report(record)
    log.info("已写入 %s；报告 %s", AUTO_PARAMS_FILE, report)
    _notify(record)
    return 0


def do_rollback(as_of: str, dry_run: bool) -> int:
    records = read_audit()
    applied = [r for r in records if r.get("action") == "apply"]
    if not applied:
        log.info("没有任何自动采纳记录，无需回滚")
        return 0

    last = applied[-1]
    before = last.get("before") or {}
    restore = {k: v for k, v in before.items() if v is not None}
    log.info("将回滚 %s 的采纳，还原 %s", last["date"], restore)
    if dry_run:
        return 0

    backup_current()
    write_auto_layer(
        restore,
        {
            "applied_at": datetime.now().isoformat(timespec="seconds"),
            "reason": f"回滚 {last['date']} 的自动采纳",
            "rollback_of": last.get("timestamp"),
        },
    )
    record = {
        "date": as_of,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "action": "rollback",
        "reason": f"回滚 {last['date']} 的自动采纳",
        "changes": restore,
        "before": last.get("changes") or {},
        "verdicts": [],
    }
    append_audit(record)
    write_report(record)
    _notify(record)
    return 0


def _notify(record: dict) -> None:
    try:
        from wecom_webhook import push_markdown_safe

        verb = "已自动采纳" if record["action"] == "apply" else "已回滚"
        body = "\n".join(f"- `{k}`: {record['before'].get(k)} → {v}" for k, v in record["changes"].items())
        push_markdown_safe(
            f"## ⚙️ 策略参数{verb} {record['date']}\n\n{body}\n\n"
            f"> 假设 {record.get('hypothesis_id') or '—'}；"
            f"明细 pm/strategy_review/{record['date']}-param-apply.md"
        )
    except Exception as exc:
        log.warning("企微推送失败：%s", exc)


def main() -> int:
    ap = argparse.ArgumentParser(description="受护栏保护的策略参数写入")
    ap.add_argument("--proposal", help="提案 JSON：{点路径: 值} 或 {\"params\": {...}}")
    ap.add_argument("--set", action="append", default=[], help="直接指定 key=value（可重复）")
    ap.add_argument("--gate-passed", action="store_true", help="PromotionGate 已通过")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true", help="还原最近一次自动采纳")
    ap.add_argument("--show", action="store_true", help="打印当前生效参数与审计流水")
    args = ap.parse_args()

    if args.show:
        for key, val in sorted(current_effective().items()):
            print(f"{key} = {val}")
        print(f"\n上次自动采纳：{last_applied_date() or '（从未）'}")
        return 0

    if args.rollback:
        return do_rollback(args.date, args.dry_run)

    proposal: dict[str, Any] = {}
    if args.proposal:
        raw = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
        proposal = raw.get("params", raw) if isinstance(raw, dict) else {}
    for item in args.set:
        if "=" not in item:
            continue
        key, _, val = item.partition("=")
        try:
            proposal[key.strip()] = json.loads(val)
        except ValueError:
            proposal[key.strip()] = val.strip()

    if not proposal:
        log.error("没有提案内容：用 --proposal 或 --set key=value")
        return 2

    return do_apply(proposal, args.gate_passed, args.date, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
