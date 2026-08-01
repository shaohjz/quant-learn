"""research/param_guard.py — 自动改参数的门卫

主人授权「门禁通过就自动写生产参数」。但 PromotionGate 只回答
「这组候选参数有没有统计证据」，它不回答「这次改动幅度是否安全」。
两件事必须分开把关，否则一次证据误判就能把止损从 5% 摆到 50%。

本模块只做后者，全部是纯函数：

1. **总开关** —— `strategy_feedback.auto_apply.enabled`，一键停掉全部自动写入
2. **白名单** —— 只有列出来的参数键允许被机器改；账户资金、webhook、风控上限都不在内
3. **边界** —— 每个键有硬上下限，越界直接拒绝而不是截断到边界（越界说明上游算错了）
4. **限幅** —— 单次相对变动上限，把大跳变夹成小步走
5. **冷却期** —— 两次自动采纳之间的最小间隔，留出观察窗
6. **单次改动数量上限** —— 一次只动几个键，出问题好归因

拒绝优先于截断：能安全夹住的夹住（限幅），说明上游可能有 bug 的直接拒（越界）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

# 无论配置怎么写，这些键永远不允许机器自动改。
HARD_DENY_PREFIXES = (
    "accounts.",
    "notify.",
    "notifier.",
    "broker.",
    "database.",
    "fees.",
    "risk.",
)

DEFAULT_COOLDOWN_DAYS = 14
DEFAULT_MAX_RELATIVE_STEP = 0.20
DEFAULT_MAX_KEYS = 3


@dataclass
class GuardConfig:
    enabled: bool = False
    require_promotion_gate: bool = True
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS
    max_relative_step: float = DEFAULT_MAX_RELATIVE_STEP
    max_keys_per_apply: int = DEFAULT_MAX_KEYS
    allowlist: tuple[str, ...] = ()
    bounds: dict[str, tuple[float, float]] = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: dict | None) -> "GuardConfig":
        node = (((config or {}).get("strategy_feedback") or {}).get("auto_apply")) or {}
        bounds_raw = node.get("bounds") or {}
        bounds: dict[str, tuple[float, float]] = {}
        for key, pair in bounds_raw.items():
            try:
                low, high = float(pair[0]), float(pair[1])
            except (TypeError, ValueError, IndexError):
                continue
            bounds[str(key)] = (min(low, high), max(low, high))
        return cls(
            enabled=bool(node.get("enabled", False)),
            require_promotion_gate=bool(node.get("require_promotion_gate", True)),
            cooldown_days=int(node.get("cooldown_days", DEFAULT_COOLDOWN_DAYS)),
            max_relative_step=float(node.get("max_relative_step", DEFAULT_MAX_RELATIVE_STEP)),
            max_keys_per_apply=int(node.get("max_keys_per_apply", DEFAULT_MAX_KEYS)),
            allowlist=tuple(str(k) for k in (node.get("allowlist") or [])),
            bounds=bounds,
        )


@dataclass
class KeyVerdict:
    key: str
    current: Any
    proposed: Any
    applied: Any = None
    status: str = "rejected"   # accepted / clamped / rejected / unchanged
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "current": self.current,
            "proposed": self.proposed,
            "applied": self.applied,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass
class GuardDecision:
    allowed: bool
    reason: str
    verdicts: list[KeyVerdict] = field(default_factory=list)

    @property
    def changes(self) -> dict[str, Any]:
        """真正要写下去的键值。"""
        return {
            v.key: v.applied
            for v in self.verdicts
            if v.status in ("accepted", "clamped")
        }

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "changes": self.changes,
            "verdicts": [v.to_dict() for v in self.verdicts],
        }


def _is_denied(key: str) -> bool:
    return any(key.startswith(prefix) for prefix in HARD_DENY_PREFIXES)


def _clamp_step(current: float, proposed: float, max_step: float) -> tuple[float, bool]:
    """把变动夹在相对步长内。current 为 0 时无法算相对步长，直接放行。"""
    if current == 0 or max_step <= 0:
        return proposed, False
    limit = abs(current) * max_step
    delta = proposed - current
    if abs(delta) <= limit:
        return proposed, False
    return current + (limit if delta > 0 else -limit), True


def _cooldown_remaining(last_applied: str | None, as_of: str, cooldown_days: int) -> int:
    if not last_applied or cooldown_days <= 0:
        return 0
    try:
        elapsed = (date.fromisoformat(as_of) - date.fromisoformat(last_applied)).days
    except ValueError:
        return 0
    return max(0, cooldown_days - elapsed)


def evaluate_proposal(
    current: dict[str, Any],
    proposed: dict[str, Any],
    guard: GuardConfig,
    gate_passed: bool,
    as_of: str,
    last_applied: str | None = None,
) -> GuardDecision:
    """判定一份参数提案能不能自动落地。

    `current` / `proposed` 都是「点路径 → 值」的扁平 dict。
    返回的 GuardDecision 即使 allowed=False 也带完整逐键理由，便于写进提案文件给人看。
    """
    verdicts: list[KeyVerdict] = []

    for key in sorted(proposed):
        new_val = proposed[key]
        old_val = current.get(key)
        verdict = KeyVerdict(key=key, current=old_val, proposed=new_val)

        if _is_denied(key):
            verdict.reason = "该键属于硬禁区（资金/通知/券商/风控），永不允许自动改"
        elif guard.allowlist and key not in guard.allowlist:
            verdict.reason = "不在 auto_apply.allowlist 中"
        elif old_val is None:
            verdict.reason = "当前值未知，拒绝盲写"
        elif isinstance(new_val, bool) or isinstance(old_val, bool):
            verdict.reason = "布尔开关不走自动调参"
        elif not isinstance(new_val, (int, float)) or not isinstance(old_val, (int, float)):
            verdict.reason = "只支持数值型参数自动调整"
        elif float(new_val) == float(old_val):
            verdict.status = "unchanged"
            verdict.applied = old_val
            verdict.reason = "与当前值相同"
        else:
            bounds = guard.bounds.get(key)
            if bounds and not (bounds[0] <= float(new_val) <= bounds[1]):
                verdict.reason = (
                    f"提案值 {new_val} 越界 [{bounds[0]}, {bounds[1]}]，"
                    f"疑似上游计算异常，拒绝而不截断"
                )
            else:
                applied, clamped = _clamp_step(
                    float(old_val), float(new_val), guard.max_relative_step
                )
                if bounds:
                    applied = max(bounds[0], min(bounds[1], applied))
                if isinstance(old_val, int) and float(applied).is_integer():
                    applied = int(applied)
                elif isinstance(old_val, int):
                    # 整数参数被夹成小数时向变动方向取整，否则会永远卡住不动。
                    applied = int(applied + (0.5 if applied > old_val else -0.5))
                    applied = max(bounds[0], min(bounds[1], applied)) if bounds else applied
                if applied == old_val:
                    verdict.status = "unchanged"
                    verdict.applied = old_val
                    verdict.reason = "限幅后与当前值相同，本轮不动"
                else:
                    verdict.status = "clamped" if clamped else "accepted"
                    verdict.applied = applied
                    verdict.reason = (
                        f"变动超过单次上限 {guard.max_relative_step:.0%}，夹到 {applied}"
                        if clamped
                        else "通过边界与限幅检查"
                    )
        verdicts.append(verdict)

    effective = [v for v in verdicts if v.status in ("accepted", "clamped")]

    if not guard.enabled:
        return GuardDecision(False, "auto_apply.enabled=false，自动写入已关闭", verdicts)
    if guard.require_promotion_gate and not gate_passed:
        return GuardDecision(False, "PromotionGate 未通过，不自动改参数", verdicts)

    remaining = _cooldown_remaining(last_applied, as_of, guard.cooldown_days)
    if remaining > 0:
        return GuardDecision(
            False,
            f"冷却期未满：上次采纳于 {last_applied}，还需 {remaining} 天",
            verdicts,
        )
    if not effective:
        return GuardDecision(False, "没有通过检查的可改参数", verdicts)
    if len(effective) > guard.max_keys_per_apply:
        return GuardDecision(
            False,
            f"本次要改 {len(effective)} 个参数，超过单次上限 "
            f"{guard.max_keys_per_apply}，拆分后再来",
            verdicts,
        )

    return GuardDecision(True, f"通过全部护栏，将改动 {len(effective)} 个参数", verdicts)


def should_rollback(
    baseline_expectancy: float | None,
    current_expectancy: float | None,
    degrade_pct: float,
) -> tuple[bool, str]:
    """采纳后观察窗内是否该回滚。

    `degrade_pct` 是相对退化阈值（0.5 表示比基线差 50% 就回滚）。
    基线为负或缺失时不用比例判断——除数是负数时比例会反向，改看是否又变差。
    """
    if current_expectancy is None:
        return False, "观察期数据不足，暂不回滚"
    if baseline_expectancy is None:
        if current_expectancy < 0:
            return True, f"无基线可比，但采纳后期望为负（{current_expectancy:+.2f}），回滚"
        return False, "无基线可比，采纳后期望非负，继续观察"
    if baseline_expectancy <= 0:
        if current_expectancy < baseline_expectancy:
            return True, (
                f"基线本就为负（{baseline_expectancy:+.2f}），采纳后进一步恶化到 "
                f"{current_expectancy:+.2f}，回滚"
            )
        return False, "未比负基线更差，继续观察"
    threshold = baseline_expectancy * (1.0 - degrade_pct)
    if current_expectancy < threshold:
        return True, (
            f"采纳后期望 {current_expectancy:+.2f} 低于退化阈值 {threshold:+.2f}"
            f"（基线 {baseline_expectancy:+.2f} 的 {1 - degrade_pct:.0%}），回滚"
        )
    return False, f"采纳后期望 {current_expectancy:+.2f} 未跌破阈值 {threshold:+.2f}"
