"""参数写入器：端到端验证「默认不写、放行才写、能回滚」。"""

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import quant_core.swing_params as swing_params
from scripts import apply_strategy_params as mod

KEY = "swing_strategy.execution.min_score_buy"
STOP = "swing_strategy.execution.stop_loss_pct"


def _cfg(enabled=True, **over):
    auto = {
        "enabled": enabled,
        "require_promotion_gate": True,
        "cooldown_days": 14,
        "max_relative_step": 0.20,
        "max_keys_per_apply": 3,
        "allowlist": [KEY, STOP],
        "bounds": {KEY: [4, 8], STOP: [0.03, 0.08]},
    }
    auto.update(over)
    return {"strategy_feedback": {"auto_apply": auto}}


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """把自动层文件和审计目录都关进 tmp_path，绝不碰真仓库。"""
    auto_file = tmp_path / "config.strategy_params.yaml"
    monkeypatch.setattr(mod, "AUTO_PARAMS_FILE", auto_file)
    monkeypatch.setattr(swing_params, "AUTO_PARAMS_FILE", auto_file)
    monkeypatch.setenv("QUANT_ARTIFACT_ROOT", str(tmp_path / "output"))
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    # 假设记账降级：本测试只验证写参数本身
    monkeypatch.setattr(mod, "open_hypothesis", lambda *a, **k: "H-TEST")
    monkeypatch.setattr(mod, "_notify", lambda record: None)
    return auto_file


def _use_config(monkeypatch, cfg):
    monkeypatch.setattr(mod, "current_effective", lambda: {KEY: 5, STOP: 0.05})
    import sim.config

    monkeypatch.setattr(sim.config, "load_config", lambda: cfg)


def test_disabled_switch_writes_nothing(sandbox, monkeypatch):
    _use_config(monkeypatch, _cfg(enabled=False))
    mod.do_apply({KEY: 6}, gate_passed=True, as_of="2026-08-01", dry_run=False)

    assert not sandbox.exists()
    audit = mod.read_audit()
    assert audit[-1]["action"] == "skip"
    assert "enabled=false" in audit[-1]["reason"]


def test_gate_failure_writes_nothing(sandbox, monkeypatch):
    _use_config(monkeypatch, _cfg())
    mod.do_apply({KEY: 6}, gate_passed=False, as_of="2026-08-01", dry_run=False)

    assert not sandbox.exists()
    assert mod.read_audit()[-1]["action"] == "skip"


def test_dry_run_writes_nothing(sandbox, monkeypatch):
    _use_config(monkeypatch, _cfg())
    mod.do_apply({KEY: 6}, gate_passed=True, as_of="2026-08-01", dry_run=True)
    assert not sandbox.exists()


def test_approved_change_is_written_to_auto_layer(sandbox, monkeypatch):
    _use_config(monkeypatch, _cfg())
    mod.do_apply({KEY: 6}, gate_passed=True, as_of="2026-08-01", dry_run=False)

    data = yaml.safe_load(sandbox.read_text(encoding="utf-8"))
    assert data["swing_strategy"]["execution"]["min_score_buy"] == 6
    assert data["meta"]["hypothesis_id"] == "H-TEST"

    record = mod.read_audit()[-1]
    assert record["action"] == "apply"
    assert record["changes"] == {KEY: 6}
    assert record["before"] == {KEY: 5}


def test_oversized_move_is_clamped_before_write(sandbox, monkeypatch):
    _use_config(monkeypatch, _cfg())
    mod.do_apply({STOP: 0.08}, gate_passed=True, as_of="2026-08-01", dry_run=False)

    data = yaml.safe_load(sandbox.read_text(encoding="utf-8"))
    written = data["swing_strategy"]["execution"]["stop_loss_pct"]
    assert abs(written - 0.06) < 1e-9  # 0.05 +20%，不是提案的 0.08


def test_out_of_bounds_proposal_is_refused(sandbox, monkeypatch):
    _use_config(monkeypatch, _cfg())
    mod.do_apply({STOP: 0.9}, gate_passed=True, as_of="2026-08-01", dry_run=False)
    assert not sandbox.exists()


def test_config_yaml_is_never_touched(sandbox, monkeypatch):
    """只写小文件；42KB 的 config.yaml 不能被机器改。"""
    real_config = Path(__file__).resolve().parents[1] / "config.yaml"
    before = real_config.read_bytes()
    _use_config(monkeypatch, _cfg())
    mod.do_apply({KEY: 6}, gate_passed=True, as_of="2026-08-01", dry_run=False)
    assert real_config.read_bytes() == before


def test_second_apply_backs_up_previous_file(sandbox, monkeypatch, tmp_path):
    _use_config(monkeypatch, _cfg(cooldown_days=0))
    mod.do_apply({KEY: 6}, gate_passed=True, as_of="2026-08-01", dry_run=False)
    monkeypatch.setattr(mod, "current_effective", lambda: {KEY: 6, STOP: 0.05})
    mod.do_apply({KEY: 7}, gate_passed=True, as_of="2026-08-02", dry_run=False)

    backups = list((tmp_path / "output" / "strategy_params" / "backup").glob("*.yaml"))
    assert len(backups) == 1
    assert yaml.safe_load(sandbox.read_text(encoding="utf-8"))["swing_strategy"]["execution"]["min_score_buy"] == 7


def test_cooldown_blocks_second_apply(sandbox, monkeypatch):
    _use_config(monkeypatch, _cfg(cooldown_days=14))
    mod.do_apply({KEY: 6}, gate_passed=True, as_of="2026-08-01", dry_run=False)
    monkeypatch.setattr(mod, "current_effective", lambda: {KEY: 6, STOP: 0.05})
    mod.do_apply({KEY: 7}, gate_passed=True, as_of="2026-08-05", dry_run=False)

    assert yaml.safe_load(sandbox.read_text(encoding="utf-8"))["swing_strategy"]["execution"]["min_score_buy"] == 6
    assert mod.read_audit()[-1]["action"] == "skip"


def test_rollback_restores_previous_value(sandbox, monkeypatch):
    _use_config(monkeypatch, _cfg())
    mod.do_apply({KEY: 6}, gate_passed=True, as_of="2026-08-01", dry_run=False)
    mod.do_rollback("2026-08-10", dry_run=False)

    data = yaml.safe_load(sandbox.read_text(encoding="utf-8"))
    assert data["swing_strategy"]["execution"]["min_score_buy"] == 5
    assert mod.read_audit()[-1]["action"] == "rollback"


def test_rollback_without_history_is_noop(sandbox, monkeypatch):
    _use_config(monkeypatch, _cfg())
    assert mod.do_rollback("2026-08-10", dry_run=False) == 0
    assert not sandbox.exists()


def test_apply_writes_human_readable_report(sandbox, monkeypatch, tmp_path):
    _use_config(monkeypatch, _cfg())
    mod.do_apply({KEY: 6}, gate_passed=True, as_of="2026-08-01", dry_run=False)

    report = tmp_path / "pm" / "strategy_review" / "2026-08-01-param-apply.md"
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "已采纳" in text
    assert KEY in text


def test_flatten_unflatten_roundtrip():
    tree = {"signals": {"rsi_oversold": 35.0}, "execution": {"min_score_buy": 5}}
    flat = mod.flatten({"swing_strategy": tree}, prefix="")
    assert flat["swing_strategy.execution.min_score_buy"] == 5
    assert mod.unflatten(flat) == tree
