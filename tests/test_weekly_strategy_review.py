"""每周策略复盘：门禁解析、提案映射、数据质量红线、回滚判定。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts import weekly_strategy_review as mod


def _optimize(**params):
    base = {
        "a_ma20_tolerance": 0.02,
        "b_ma10_tolerance": 0.015,
        "max_volume_ratio": 0.8,
        "min_expected_rr": 1.2,
        "min_score": 7,
    }
    base.update(params)
    return {"accounts": {"account3": {"final_best_params": base}}, "audit": {}}


CURRENT = {
    "swing_strategy.signals.a_ma20_tolerance": 0.015,
    "swing_strategy.signals.b_ma10_tolerance": 0.01,
    "swing_strategy.signals.max_volume_ratio": 0.8,
    "swing_strategy.filters.min_net_rr": 1.2,
    "swing_strategy.execution.min_score_buy": 5,
}


def test_proposal_maps_research_names_to_config_keys():
    proposal, _ = mod.build_proposal(_optimize(), CURRENT)
    assert proposal["swing_strategy.execution.min_score_buy"] == 7
    assert proposal["swing_strategy.signals.a_ma20_tolerance"] == 0.02


def test_unchanged_params_are_left_out_of_proposal():
    """max_volume_ratio 与 min_expected_rr 和当前值相同，不该进提案。"""
    proposal, _ = mod.build_proposal(_optimize(), CURRENT)
    assert "swing_strategy.signals.max_volume_ratio" not in proposal
    assert "swing_strategy.filters.min_net_rr" not in proposal


def test_unmapped_param_is_reported_not_silently_dropped():
    proposal, notes = mod.build_proposal(_optimize(some_new_knob=1), CURRENT)
    assert "swing_strategy" not in str(proposal.get("some_new_knob"))
    assert any("some_new_knob" in n for n in notes)


def test_empty_optimize_yields_empty_proposal():
    proposal, _ = mod.build_proposal({}, CURRENT)
    assert proposal == {}


def test_research_only_flag_is_detected():
    assert mod.research_only({"audit": {"research_only": True}}) is True
    assert mod.research_only({"audit": {}}) is False
    assert mod.research_only({}) is False


def test_gate_passes_when_a_strategy_can_promote():
    gate = {
        "accounts": {
            "3": {"strategies": [{"strategy": "A|B", "promotion": {"can_promote": True}}]}
        }
    }
    ok, reason = mod.gate_verdict(gate)
    assert ok
    assert "A|B" in reason


def test_gate_blocks_and_surfaces_reasons():
    gate = {
        "accounts": {
            "3": {
                "strategies": [
                    {
                        "strategy": "A|B",
                        "promotion": {
                            "can_promote": False,
                            "blockers": ["闭环交易不足 100 笔", "OOS 正窗口比例不达标"],
                        },
                    }
                ]
            }
        }
    }
    ok, reason = mod.gate_verdict(gate)
    assert not ok
    assert "100 笔" in reason


def test_missing_account_is_treated_as_not_passed():
    ok, reason = mod.gate_verdict({"accounts": {}})
    assert not ok
    assert "没有该账户" in reason


def test_malformed_gate_never_passes():
    """门禁结构异常时必须保守判不通过，不能因解析失败放行改参。"""
    for bad in ({}, {"accounts": None}, {"accounts": {"3": {}}}, {"accounts": {"3": {"strategies": []}}}):
        ok, _ = mod.gate_verdict(bad)
        assert not ok


def test_rollback_skipped_without_apply_history(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "read_audit", lambda: [])
    should, reason = mod.check_rollback("2026-08-20", {"auto_apply": {"rollback": {"enabled": True}}})
    assert not should
    assert "没有自动采纳记录" in reason


def test_rollback_waits_for_observation_window(monkeypatch):
    monkeypatch.setattr(
        mod, "read_audit", lambda: [{"action": "apply", "date": "2026-08-18", "baseline_expectancy": 0.01}]
    )
    should, reason = mod.check_rollback(
        "2026-08-20", {"auto_apply": {"rollback": {"enabled": True, "watch_days": 10}}}
    )
    assert not should
    assert "观察期未满" in reason


def test_rollback_disabled_by_config(monkeypatch):
    monkeypatch.setattr(mod, "read_audit", lambda: [{"action": "apply", "date": "2026-01-01"}])
    should, reason = mod.check_rollback("2026-08-20", {"auto_apply": {"rollback": {"enabled": False}}})
    assert not should
    assert "已关闭" in reason


def test_rollback_triggers_when_scorecard_degrades(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANT_ARTIFACT_ROOT", str(tmp_path))
    card_dir = tmp_path / "strategy_scorecard"
    card_dir.mkdir(parents=True)
    (card_dir / "latest.json").write_text(
        '{"windows": {"60d": {"overall": {"mean_fwd_5d": 0.001}}}}', encoding="utf-8"
    )
    monkeypatch.setattr(
        mod,
        "read_audit",
        lambda: [{"action": "apply", "date": "2026-08-01", "baseline_expectancy": 0.02}],
    )
    should, reason = mod.check_rollback(
        "2026-08-20", {"auto_apply": {"rollback": {"enabled": True, "watch_days": 10, "degrade_pct": 0.5}}}
    )
    assert should
    assert "低于退化阈值" in reason
