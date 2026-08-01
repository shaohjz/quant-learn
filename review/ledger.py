"""review/ledger.py — 假设记账与策略漂移检测。

「自我改进」和「随机游走」的区别只有一条：改动之前有没有写下可证伪的预期。
没有这一步，改完一周赚了就以为找对了，亏了就再改回去，一年下来参数转了一圈
回到原点，什么也没学到。

所以这里强制两件事：

1. 每次改策略参数都要开一条假设，写明预期什么、多久之后看、至少要几笔样本。
   到期由系统核对，结论落盘，成为下次决策的依据。
2. 每天给策略参数拍快照。参数变了却没有对应的假设 —— 那是无记录的静默改参，
   直接报 P0。这条是整个闭环的守门员。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER_DIR = PROJECT_ROOT / "pm" / "strategy_review"

STATUS_OPEN = "open"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"
STATUS_INCONCLUSIVE = "inconclusive"
STATUS_ABANDONED = "abandoned"


@dataclass
class Hypothesis:
    id: str
    created: str
    title: str
    layer: str
    param: str = ""
    before: Any = None
    after: Any = None
    expect: str = ""
    metric: str = ""
    baseline: float | None = None
    target: float | None = None
    review_after: str = ""
    min_samples: int = 20
    status: str = STATUS_OPEN
    outcome: str = ""
    closed: str = ""
    source_finding: str = ""

    def is_due(self, today: str) -> bool:
        return self.status == STATUS_OPEN and bool(self.review_after) and today >= self.review_after

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ParamDrift:
    strategy_id: str
    param: str
    before: Any
    after: Any
    matched_hypothesis: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LedgerState:
    hypotheses: list[Hypothesis] = field(default_factory=list)
    drifts: list[ParamDrift] = field(default_factory=list)
    snapshot_written: bool = False
    previous_snapshot_date: str = ""

    def open_items(self) -> list[Hypothesis]:
        return [h for h in self.hypotheses if h.status == STATUS_OPEN]

    def due_items(self, today: str) -> list[Hypothesis]:
        return [h for h in self.hypotheses if h.is_due(today)]

    def unexplained_drifts(self) -> list[ParamDrift]:
        return [d for d in self.drifts if not d.matched_hypothesis]

    def to_dict(self) -> dict:
        return {
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "drifts": [d.to_dict() for d in self.drifts],
            "snapshot_written": self.snapshot_written,
            "previous_snapshot_date": self.previous_snapshot_date,
        }


class Ledger:
    """假设与快照的持久化。落盘为 JSON，方便 git diff 看出改了什么。"""

    def __init__(self, base_dir: Path | None = None):
        self.dir = Path(base_dir) if base_dir else DEFAULT_LEDGER_DIR
        self.hypo_file = self.dir / "hypotheses.json"
        self.snapshot_file = self.dir / "spec_snapshots.json"

    # ── 假设 ──

    def load_hypotheses(self) -> list[Hypothesis]:
        raw = _read_json(self.hypo_file, default=[])
        out = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            known = {k: item.get(k) for k in Hypothesis.__dataclass_fields__ if k in item}
            known.setdefault("id", "")
            known.setdefault("created", "")
            known.setdefault("title", "")
            known.setdefault("layer", "")
            out.append(Hypothesis(**known))
        return out

    def save_hypotheses(self, items: list[Hypothesis]) -> None:
        _write_json(self.hypo_file, [h.to_dict() for h in items])

    def next_id(self, items: list[Hypothesis]) -> str:
        nums = []
        for h in items:
            if h.id.startswith("H-"):
                try:
                    nums.append(int(h.id[2:]))
                except ValueError:
                    continue
        return f"H-{max(nums, default=0) + 1:03d}"

    def open_hypothesis(
        self,
        title: str,
        layer: str,
        *,
        today: str,
        param: str = "",
        before: Any = None,
        after: Any = None,
        expect: str = "",
        metric: str = "",
        baseline: float | None = None,
        target: float | None = None,
        horizon_days: int = 21,
        min_samples: int = 20,
        source_finding: str = "",
    ) -> Hypothesis:
        items = self.load_hypotheses()
        review_after = (date.fromisoformat(today) + timedelta(days=horizon_days)).isoformat()
        h = Hypothesis(
            id=self.next_id(items),
            created=today,
            title=title,
            layer=layer,
            param=param,
            before=before,
            after=after,
            expect=expect,
            metric=metric,
            baseline=baseline,
            target=target,
            review_after=review_after,
            min_samples=min_samples,
            source_finding=source_finding,
        )
        items.append(h)
        self.save_hypotheses(items)
        return h

    def close_hypothesis(self, hypo_id: str, status: str, outcome: str, today: str) -> Hypothesis | None:
        items = self.load_hypotheses()
        target = next((h for h in items if h.id == hypo_id), None)
        if target is None:
            return None
        target.status = status
        target.outcome = outcome
        target.closed = today
        self.save_hypotheses(items)
        return target

    # ── 快照与漂移 ──

    def load_snapshots(self) -> list[dict]:
        raw = _read_json(self.snapshot_file, default=[])
        return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []

    def record_snapshot(self, specs: list[Any], today: str, keep: int = 400) -> tuple[list[ParamDrift], str, bool]:
        """记录今日参数快照，并与上一份不同日期的快照比对。

        返回 (漂移列表, 上一份快照日期, 是否新写入)。同日重复跑会覆盖当天那条，
        比对基准始终是「上一个有记录的日子」，因此一天跑多次不会把漂移吃掉。
        """
        snaps = self.load_snapshots()
        current = {
            "date": today,
            "specs": {
                s.strategy_id: {
                    "spec_hash": s.spec_hash(),
                    "params": {p.key: p.to_dict()["value"] for p in s.params},
                }
                for s in specs
            },
        }

        prior = [s for s in snaps if s.get("date") != today]
        prior.sort(key=lambda s: str(s.get("date") or ""))
        previous = prior[-1] if prior else None

        drifts: list[ParamDrift] = []
        if previous:
            for sid, cur in current["specs"].items():
                old = (previous.get("specs") or {}).get(sid) or {}
                old_params = old.get("params") or {}
                for key, new_val in (cur.get("params") or {}).items():
                    if key in old_params and old_params[key] != new_val:
                        drifts.append(ParamDrift(sid, key, old_params[key], new_val))

        existing_today = next((s for s in snaps if s.get("date") == today), None)
        written = existing_today != current
        snaps = [s for s in snaps if s.get("date") != today] + [current]
        snaps.sort(key=lambda s: str(s.get("date") or ""))
        _write_json(self.snapshot_file, snaps[-keep:])

        return drifts, str(previous.get("date")) if previous else "", written

    # ── 组装 ──

    def build_state(self, specs: list[Any], today: str) -> LedgerState:
        drifts, prev_date, written = self.record_snapshot(specs, today)
        hypos = self.load_hypotheses()

        # 漂移能对上一条开着的假设，就算「有记录的改动」
        for d in drifts:
            full = f"{d.strategy_id}.{d.param}"
            match = next(
                (h for h in hypos if h.status == STATUS_OPEN and h.param in (full, d.param)),
                None,
            )
            if match:
                d.matched_hypothesis = match.id

        return LedgerState(
            hypotheses=hypos,
            drifts=drifts,
            snapshot_written=written,
            previous_snapshot_date=prev_date,
        )


def check_ledger(state: LedgerState, today: str) -> list[Any]:
    """把记账层的异常转成 Finding：静默改参、假设到期未核对。"""
    from review.diagnostics import Finding

    out: list[Finding] = []

    for d in state.unexplained_drifts():
        out.append(Finding(
            rule_id="unlogged_param_change",
            subject=f"{d.strategy_id}.{d.param}",
            severity="P0",
            layer="execution",
            title=f"参数「{d.strategy_id}.{d.param}」被改过，但没有对应的假设记录",
            evidence=[f"{d.before} → {d.after}（对比 {state.previous_snapshot_date} 的快照）"],
            why="改动没有预期就无法验证，等于放弃了这次改动本可以提供的信息。",
            action=f"补一条假设说明为什么改、期望什么指标变好、多久后核对：\n"
                   f"  python scripts/strategy_review.py --open-hypothesis "
                   f"--param {d.strategy_id}.{d.param} --expect '...'",
            data=d.to_dict(),
        ))

    for h in state.due_items(today):
        out.append(Finding(
            rule_id="hypothesis_due",
            subject=h.id,
            severity="P1",
            layer=h.layer or "parameter",
            title=f"假设 {h.id} 到期待核对：{h.title}",
            evidence=[
                f"立于 {h.created}，约定 {h.review_after} 复核，最少 {h.min_samples} 笔样本",
                f"预期：{h.expect}" if h.expect else "（未写预期，下次记得写）",
            ],
            why="到期不核对，假设就退化成没人负责的历史遗留。",
            action=f"核对后结案：python scripts/strategy_review.py --close-hypothesis {h.id} "
                   f"--status confirmed|rejected|inconclusive --outcome '...'",
            data=h.to_dict(),
        ))

    return out


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
