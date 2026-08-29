"""银行股专用波段：池 + profile 切换（无行情依赖）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from quant_core.bank_swing_pool import BANK_POOL, get_bank_pool, is_bank_code


def test_bank_pool_size_and_unique():
    pool = get_bank_pool()
    assert len(pool) == len(BANK_POOL)
    assert len(pool) >= 12
    codes = [c[-6:] for c, _ in pool]
    assert len(codes) == len(set(codes))
    assert all(n.endswith("银行") or "银行" in n for _, n in pool)


def test_is_bank_code():
    assert is_bank_code("600036")
    assert is_bank_code("sh600036")
    assert is_bank_code("000001")
    assert not is_bank_code("600519")


def test_apply_bank_profile_overrides(tmp_path, monkeypatch):
    import swing_daily_report as sdr

    from scripts.bank_swing_daily import apply_bank_profile

    # 隔离 OUT_DIR，避免写真实产物
    monkeypatch.setenv("QUANT_ARTIFACT_ROOT", str(tmp_path))
    # config_resolver 可能已缓存；直接改 profile 后断言
    apply_bank_profile()
    assert sdr.SWING_ACCOUNT_ID == 4
    assert sdr.SWING_ACCOUNT_NAME == "bank_swing"
    assert sdr.REPORT_TITLE == "银行波段结论"
    assert sdr.VERDICT_LABEL == "银行波段"
    assert sdr.SKIP_GENERAL_POOL is True
    assert sdr.SKIP_INTRADAY_MERGE is True
    assert sdr.MAX_POSITIONS == 3
    pool = sdr.get_stock_pool()
    assert any(c.endswith("600036") for c, _ in pool)

    # 结论文案带银行标签
    snap = {
        "cash": 30000, "market_value": 0, "total": 30000,
        "cum_pnl": 0, "cum_pct": 0, "positions": [],
    }
    c = sdr.build_conclusion("2026-08-21", snap, [], [], day_pnl=120.0, day_pct=0.4)
    assert "银行波段" in c["verdict"]
    assert "赚" in c["verdict"]
    md = sdr.render_markdown(c)
    assert md.startswith("# 银行波段结论")
    assert "bank_swing" in md or "#4" in md


def test_bank_params_come_from_bank_section(monkeypatch, tmp_path):
    """银行池必须读 bank_swing_strategy: 段，而不是 #3 的 swing_strategy:。

    银行股波动小、股价低，通用参数下 16 只 0 只可买（2026-08-29 实测）。
    银行池需要自己的盈亏比门槛与可执行信号类型，且不能反向影响 #3。
    """
    import swing_daily_report as sdr

    from scripts.bank_swing_daily import apply_bank_profile
    from sim import config as sim_config

    cfg = {
        "swing_strategy": {
            "filters": {"min_net_rr": 1.2},
            "execution": {"executable_types": ["A", "B"], "single_budget": 10000.0},
        },
        "bank_swing_strategy": {
            "filters": {"min_net_rr": 1.0},
            "execution": {
                "executable_types": ["A", "B", "C", "D"],
                "single_budget": 8000.0,
            },
        },
    }
    monkeypatch.setattr(sim_config, "load_config", lambda: cfg)
    monkeypatch.setenv("QUANT_ARTIFACT_ROOT", str(tmp_path))

    apply_bank_profile()

    assert sdr.PARAMS.min_net_rr == 1.0
    assert sdr.PARAMS.single_budget == 8000.0
    assert sdr.EXECUTABLE_TYPES == {"A", "B", "C", "D"}
    assert sdr.SCAN_FEE_BUDGET == 8000.0


def test_bank_params_fall_back_to_defaults_without_section(monkeypatch, tmp_path):
    """未配置 bank_swing_strategy: 段时必须回退到默认值，行为与之前一致。"""
    import swing_daily_report as sdr

    from scripts.bank_swing_daily import apply_bank_profile
    from sim import config as sim_config

    cfg = {"swing_strategy": {"execution": {"max_positions": 5}}}
    monkeypatch.setattr(sim_config, "load_config", lambda: cfg)
    monkeypatch.setenv("QUANT_ARTIFACT_ROOT", str(tmp_path))

    apply_bank_profile()

    # 通用段的配置不应泄漏到银行池
    assert sdr.MAX_POSITIONS == 3
    assert sdr.PARAMS.single_budget == 10000.0
    assert sdr.PARAMS.min_net_rr == 1.2
    assert sdr.EXECUTABLE_TYPES == {"A", "B"}
