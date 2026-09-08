"""银行股专用波段：池 + profile 切换（无行情依赖）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from quant_core.bank_swing_pool import BANK_POOL, get_bank_pool, is_bank_code


@pytest.fixture(autouse=True)
def _restore_swing_auto_params():
    """apply_bank_profile 会改 swing_auto.PARAMS，测完必须还原，避免污染 #3。"""
    import swing_auto as sa

    orig = sa.PARAMS
    yield
    sa.PARAMS = orig


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
    assert sdr.MIN_SCORE_BUY == 3
    assert sdr.PARAMS.max_volume_ratio == 0.95
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
            "signals": {"max_volume_ratio": 0.95},
            "filters": {"min_net_rr": 1.0},
            "execution": {
                "executable_types": ["A", "B", "C", "D"],
                "single_budget": 8000.0,
                "min_score_buy": 3,
            },
        },
    }
    monkeypatch.setattr(sim_config, "load_config", lambda: cfg)
    monkeypatch.setenv("QUANT_ARTIFACT_ROOT", str(tmp_path))

    apply_bank_profile()

    import swing_auto as sa

    assert sdr.PARAMS.min_net_rr == 1.0
    assert sdr.PARAMS.single_budget == 8000.0
    assert sdr.PARAMS.min_score_buy == 3
    assert sdr.PARAMS.max_volume_ratio == 0.95
    assert sdr.MIN_SCORE_BUY == 3
    assert sdr.EXECUTABLE_TYPES == {"A", "B", "C", "D"}
    assert sdr.SCAN_FEE_BUDGET == 8000.0
    # 扫描层必须一起切，否则 scan_stock 仍读 #3 的 1.2 / 0.8
    assert sa.PARAMS is sdr.PARAMS
    assert sa.PARAMS.min_net_rr == 1.0
    assert sa.PARAMS.max_volume_ratio == 0.95


def test_initial_cash_failure_falls_back_with_warning(monkeypatch, tmp_path, caplog):
    """读不到账户初始资金时必须兜底 3 万并留下日志，不能静默吞掉。

    这里曾被 `except Exception: pass` 静默吞掉：配置一坏银行日报就当无事发生，
    用错误的本金算净值，且日志里查不到任何线索。
    """
    import logging

    import swing_daily_report as sdr

    import scripts.bank_swing_daily as bsd

    monkeypatch.setenv("QUANT_ARTIFACT_ROOT", str(tmp_path))

    def boom(_account_id):
        raise OSError("config.yaml 被其它进程占用")

    monkeypatch.setattr(bsd, "account_initial_cash", boom)

    with caplog.at_level(logging.WARNING):
        bsd.apply_bank_profile()

    assert sdr.SWING_INITIAL_CASH == 30_000.0
    assert "初始资金" in caplog.text
    assert "config.yaml 被其它进程占用" in caplog.text


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
    assert sdr.PARAMS.min_score_buy == 5
    assert sdr.PARAMS.max_volume_ratio == 0.8
    assert sdr.EXECUTABLE_TYPES == {"A", "B"}


def test_real_config_bank_section_loosens_score_and_volume():
    """config.yaml 银行段必须比 #3 更松：单信号可买、量比放到 0.95。"""
    from quant_core.swing_params import load_swing_params

    bank = load_swing_params(section="bank_swing_strategy", auto_overrides={})
    generic = load_swing_params(section="swing_strategy", auto_overrides={})
    assert bank.min_score_buy == 3
    assert bank.max_volume_ratio == 0.95
    assert generic.min_score_buy == 5
    assert generic.max_volume_ratio == 0.8


def test_run_scan_forwards_module_params(monkeypatch):
    """银行日报改的是 sdr.PARAMS，run_scan 必须把它传进 scan_stock。"""
    import swing_daily_report as sdr

    seen: dict = {}

    def fake_scan(code, name, fee_budget=None, params=None):
        seen["params"] = params
        seen["fee_budget"] = fee_budget
        return None

    monkeypatch.setattr(sdr, "scan_stock", fake_scan)
    monkeypatch.setattr(sdr, "get_stock_pool", lambda: [("sh601328", "交通银行")])
    monkeypatch.setattr(sdr, "save_results", lambda *_a, **_k: None)
    monkeypatch.setattr(sdr.time, "sleep", lambda *_a: None)

    assert sdr.run_scan() == []
    assert seen["params"] is sdr.PARAMS
    assert seen["fee_budget"] is sdr.SCAN_FEE_BUDGET


def test_pick_buys_allows_single_b_when_min_score_is_3(monkeypatch):
    """A=4 / B=3。min_score_buy=5 时单次回踩永远买不了。"""
    import swing_daily_report as sdr

    row = {
        "code": "601328",
        "name": "交通银行",
        "signal_type": "B",
        "score": 3,
        "price": 7.28,
        "support": 7.0,
        "resist": 7.5,
        "net_rr": 2.66,
    }
    monkeypatch.setattr(sdr, "EXECUTABLE_TYPES", {"A", "B", "C", "D"})
    monkeypatch.setattr(sdr, "MAX_POSITIONS", 3)
    monkeypatch.setattr(sdr, "MIN_SCORE_BUY", 5)
    assert sdr.pick_buys([row], []) == []

    monkeypatch.setattr(sdr, "MIN_SCORE_BUY", 3)
    picks = sdr.pick_buys([row], [])
    assert len(picks) == 1
    assert picks[0]["code"] == "601328"


def test_scan_stock_uses_passed_volume_threshold(monkeypatch):
    """量比 0.85：#3 的 0.8 滤掉，#4 的 0.95 应出 B 信号。"""
    import swing_auto as sa
    from quant_core.swing_params import load_swing_params

    price = 10.0
    klines = []
    for i in range(30):
        close = 9.5 if i < 20 else 10.0
        klines.append({
            "date": f"2026-01-{i + 1:02d}",
            "open": close,
            "close": close,
            "high": close * 1.04,
            "low": close * 0.96,
            "volume": 10000.0 if i < 29 else 8500.0,
        })

    monkeypatch.setattr(sa, "get_quote", lambda _c: {
        "price": price, "change_pct": 0.2, "pe_ttm": 6.0,
    })
    monkeypatch.setattr(sa, "get_kline", lambda _c, _d=30: klines)

    p3 = load_swing_params(section="swing_strategy", auto_overrides={})
    p4 = load_swing_params(section="bank_swing_strategy", auto_overrides={})
    assert p3.max_volume_ratio == 0.8
    assert p4.max_volume_ratio == 0.95

    assert sa.scan_stock("sh601328", "交通银行", fee_budget=8000.0, params=p3) is None
    hit = sa.scan_stock("sh601328", "交通银行", fee_budget=8000.0, params=p4)
    assert hit is not None
    assert hit["signal_type"] == "B"
    assert hit["score"] == 3
