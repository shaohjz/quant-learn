"""自动改参数的护栏。

主人授权「门禁通过就自动写生产参数」，所以这组测试是最后一道防线：
证明即使 PromotionGate 放行，越界、超幅、冷却期内、禁区键都改不动。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.param_guard import (
    GuardConfig,
    evaluate_proposal,
    should_rollback,
)

ALLOW = ("swing_strategy.execution.min_score_buy", "swing_strategy.execution.stop_loss_pct")


def _guard(**kw) -> GuardConfig:
    base = dict(
        enabled=True,
        require_promotion_gate=True,
        cooldown_days=14,
        max_relative_step=0.20,
        max_keys_per_apply=3,
        allowlist=ALLOW,
        bounds={
            "swing_strategy.execution.min_score_buy": (4, 8),
            "swing_strategy.execution.stop_loss_pct": (0.03, 0.08),
        },
    )
    base.update(kw)
    return GuardConfig(**base)


def test_master_switch_blocks_everything():
    d = evaluate_proposal(
        {"swing_strategy.execution.min_score_buy": 5},
        {"swing_strategy.execution.min_score_buy": 6},
        _guard(enabled=False),
        gate_passed=True,
        as_of="2026-08-01",
    )
    assert not d.allowed
    assert "enabled=false" in d.reason


def test_gate_failure_blocks_apply():
    d = evaluate_proposal(
        {"swing_strategy.execution.min_score_buy": 5},
        {"swing_strategy.execution.min_score_buy": 6},
        _guard(),
        gate_passed=False,
        as_of="2026-08-01",
    )
    assert not d.allowed
    assert "PromotionGate" in d.reason


def test_happy_path_applies_within_bounds_and_step():
    d = evaluate_proposal(
        {"swing_strategy.execution.min_score_buy": 5},
        {"swing_strategy.execution.min_score_buy": 6},
        _guard(),
        gate_passed=True,
        as_of="2026-08-01",
    )
    assert d.allowed
    assert d.changes == {"swing_strategy.execution.min_score_buy": 6}


def test_out_of_bounds_is_rejected_not_clamped():
    """越界说明上游算错了，截断到边界会掩盖 bug。"""
    d = evaluate_proposal(
        {"swing_strategy.execution.stop_loss_pct": 0.05},
        {"swing_strategy.execution.stop_loss_pct": 0.50},
        _guard(),
        gate_passed=True,
        as_of="2026-08-01",
    )
    assert not d.allowed
    verdict = d.verdicts[0]
    assert verdict.status == "rejected"
    assert "越界" in verdict.reason
    assert d.changes == {}


def test_large_move_is_clamped_to_step_limit():
    d = evaluate_proposal(
        {"swing_strategy.execution.stop_loss_pct": 0.05},
        {"swing_strategy.execution.stop_loss_pct": 0.08},
        _guard(),
        gate_passed=True,
        as_of="2026-08-01",
    )
    assert d.allowed
    # 单次最多动 20% → 0.05 * 1.2 = 0.06
    assert abs(d.changes["swing_strategy.execution.stop_loss_pct"] - 0.06) < 1e-9
    assert d.verdicts[0].status == "clamped"


def test_cooldown_blocks_second_apply():
    d = evaluate_proposal(
        {"swing_strategy.execution.min_score_buy": 5},
        {"swing_strategy.execution.min_score_buy": 6},
        _guard(cooldown_days=14),
        gate_passed=True,
        as_of="2026-08-01",
        last_applied="2026-07-25",
    )
    assert not d.allowed
    assert "冷却期" in d.reason


def test_cooldown_expired_allows_apply():
    d = evaluate_proposal(
        {"swing_strategy.execution.min_score_buy": 5},
        {"swing_strategy.execution.min_score_buy": 6},
        _guard(cooldown_days=14),
        gate_passed=True,
        as_of="2026-08-20",
        last_applied="2026-07-25",
    )
    assert d.allowed


def test_key_outside_allowlist_is_rejected():
    d = evaluate_proposal(
        {"swing_strategy.execution.max_positions": 3},
        {"swing_strategy.execution.max_positions": 5},
        _guard(),
        gate_passed=True,
        as_of="2026-08-01",
    )
    assert not d.allowed
    assert "allowlist" in d.verdicts[0].reason


def test_hard_deny_keys_never_writable_even_if_allowlisted():
    """账户资金/webhook/风控就算被写进 allowlist 也不许机器动。"""
    for key, val in (
        ("accounts.swing.initial_cash", 999999),
        ("notify.wecom_webhook", 1),
        ("risk.stop_loss_pct", -0.2),
        ("fees.commission_rate", 0.0),
    ):
        d = evaluate_proposal(
            {key: 1},
            {key: val},
            _guard(allowlist=(key,), bounds={}),
            gate_passed=True,
            as_of="2026-08-01",
        )
        assert not d.allowed, key
        assert "硬禁区" in d.verdicts[0].reason


def test_too_many_keys_at_once_is_blocked():
    current = {f"swing_strategy.execution.k{i}": 10 for i in range(4)}
    proposed = {f"swing_strategy.execution.k{i}": 11 for i in range(4)}
    d = evaluate_proposal(
        current,
        proposed,
        _guard(allowlist=tuple(current), bounds={}, max_keys_per_apply=3),
        gate_passed=True,
        as_of="2026-08-01",
    )
    assert not d.allowed
    assert "超过单次上限" in d.reason


def test_unknown_current_value_is_not_blindly_written():
    d = evaluate_proposal(
        {},
        {"swing_strategy.execution.min_score_buy": 6},
        _guard(),
        gate_passed=True,
        as_of="2026-08-01",
    )
    assert not d.allowed
    assert "当前值未知" in d.verdicts[0].reason


def test_identical_value_is_marked_unchanged():
    d = evaluate_proposal(
        {"swing_strategy.execution.min_score_buy": 5},
        {"swing_strategy.execution.min_score_buy": 5},
        _guard(),
        gate_passed=True,
        as_of="2026-08-01",
    )
    assert not d.allowed
    assert d.verdicts[0].status == "unchanged"


def test_integer_param_moves_at_least_one_step():
    """min_score 是整数；限幅算出 6.0 以下小数时不能永远卡在原值。"""
    d = evaluate_proposal(
        {"swing_strategy.execution.min_score_buy": 5},
        {"swing_strategy.execution.min_score_buy": 8},
        _guard(max_relative_step=0.10),
        gate_passed=True,
        as_of="2026-08-01",
    )
    assert d.allowed
    assert d.changes["swing_strategy.execution.min_score_buy"] == 6


def test_boolean_switches_are_not_auto_tuned():
    d = evaluate_proposal(
        {"swing_strategy.execution.flag": False},
        {"swing_strategy.execution.flag": True},
        _guard(allowlist=("swing_strategy.execution.flag",), bounds={}),
        gate_passed=True,
        as_of="2026-08-01",
    )
    assert not d.allowed
    assert "布尔" in d.verdicts[0].reason


def test_rollback_when_expectancy_degrades_past_threshold():
    should, reason = should_rollback(200.0, 50.0, degrade_pct=0.5)
    assert should
    assert "低于退化阈值" in reason


def test_no_rollback_when_within_tolerance():
    should, _ = should_rollback(200.0, 150.0, degrade_pct=0.5)
    assert not should


def test_negative_baseline_uses_absolute_comparison():
    """基线为负时比例判断会反向，必须改看是否更差。"""
    should, _ = should_rollback(-100.0, -150.0, degrade_pct=0.5)
    assert should
    should, _ = should_rollback(-100.0, -50.0, degrade_pct=0.5)
    assert not should


def test_insufficient_observation_does_not_rollback():
    should, reason = should_rollback(200.0, None, degrade_pct=0.5)
    assert not should
    assert "数据不足" in reason
