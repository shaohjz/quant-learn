"""波段参数层：默认值必须与迁移前的生产常量逐个相等。

这组断言是「参数搬进 config 但行为不变」的唯一保证。
数字来自 2026-07-31 迁移前的 scripts/swing_auto.py 与 scripts/swing_daily_report.py，
改动它们等于改动生产策略，必须走部署文档。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.swing_params import DEFAULTS, load_swing_params, resolve_params_dict


def test_defaults_match_pre_migration_production_constants():
    p = load_swing_params(config={}, auto_overrides={})

    # swing_auto.py 信号判定
    assert p.a_ma20_tolerance == 0.015
    assert p.b_ma10_tolerance == 0.01
    assert p.max_volume_ratio == 0.8
    assert p.quiet_volume_ratio == 0.7
    assert p.rsi_oversold == 35.0
    assert p.boll_lower_tolerance == 0.01
    assert p.e_min_change_pct == -1.5
    assert p.f_max_change_pct == -2.0

    # swing_auto.py 最终筛选
    assert p.min_net_rr == 1.2
    assert p.min_upside_pct == 0.005
    assert p.min_avg_amp == 1.0

    # swing_daily_report.py 执行层
    assert p.min_score_buy == 5
    assert p.executable_types == frozenset({"A", "B"})
    assert p.stop_loss_pct == 0.05
    assert p.take_profit_pct == 0.08
    assert p.max_positions == 3
    assert p.single_budget == 10_000.0


def test_config_yaml_overrides_defaults():
    p = load_swing_params(
        config={"swing_strategy": {"execution": {"min_score_buy": 6}}},
        auto_overrides={},
    )
    assert p.min_score_buy == 6
    assert p.stop_loss_pct == 0.05  # 未声明的仍走默认
    assert "config.yaml" in p.source_layers


def test_auto_layer_wins_over_config_yaml():
    p = load_swing_params(
        config={"swing_strategy": {"execution": {"min_score_buy": 6}}},
        auto_overrides={"execution": {"min_score_buy": 7}},
    )
    assert p.min_score_buy == 7
    assert p.source_layers == ("defaults", "config.yaml", "config.strategy_params.yaml")


def test_partial_override_does_not_drop_sibling_keys():
    merged, _ = resolve_params_dict(
        {"swing_strategy": {"signals": {"max_volume_ratio": 0.75}}}, {}
    )
    assert merged["signals"]["max_volume_ratio"] == 0.75
    assert merged["signals"]["a_ma20_tolerance"] == DEFAULTS["signals"]["a_ma20_tolerance"]
    assert merged["execution"]["stop_loss_pct"] == DEFAULTS["execution"]["stop_loss_pct"]


def test_executable_types_accepts_comma_string():
    p = load_swing_params(
        config={"swing_strategy": {"execution": {"executable_types": "A, B, C"}}},
        auto_overrides={},
    )
    assert p.executable_types == frozenset({"A", "B", "C"})


def test_fingerprint_changes_with_params():
    base = load_swing_params(config={}, auto_overrides={})
    tuned = load_swing_params(config={}, auto_overrides={"execution": {"min_score_buy": 7}})
    assert base.fingerprint() != tuned.fingerprint()
    assert len(base.fingerprint()) == 12
