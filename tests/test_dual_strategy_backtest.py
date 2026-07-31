"""双账户研究回测集成测试。"""

from datetime import date as Date

import pandas as pd
import pytest

from research.dual_strategy_backtest import (
    DataAudit,
    load_csv_directory,
    optimize_dual_strategies,
    run_dual_strategy_backtest,
)
from research.portfolio_backtest import BacktestConfig
from research.walk_forward import WalkForwardConfig


def _bars(periods: int = 70, *, raw: bool = True) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=periods)
    closes = [10.0] * periods
    opens = [10.0] * periods
    volumes = [1_000_000.0] * periods
    # 先完成 30 根 warmup，第 31 根同时命中 #1 MA10 buy_zone 与 #3 A/B，且缩量。
    volumes[30] = 100_000.0
    # 次日以正常 K 线成交，再下一日收盘触发两账户各自的成本止盈。
    if periods > 32:
        closes[32] = 11.6
    frame = pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": [max(o, c) + 0.5 for o, c in zip(opens, closes)],
            "low": [min(o, c) - 0.05 for o, c in zip(opens, closes)],
            "close": closes,
            "volume": volumes,
        }
    )
    if raw:
        frame["adjustment_type"] = "raw"
    return frame


def test_both_account_strategies_buy_and_sell_through_portfolio_constraints():
    frame = _bars()
    start = pd.Timestamp(frame.iloc[30]["date"]).date()
    end = pd.Timestamp(frame.iloc[35]["date"]).date()

    payload = run_dual_strategy_backtest(
        {"600001": frame},
        start=start,
        end=end,
        backtest_config=BacktestConfig(
            initial_cash=100_000,
            max_position_pct=0.2,
            max_positions=1,
            max_daily_new_positions=1,
        ),
    )

    for account in ("account1", "account3"):
        trades = payload["accounts"][account]["trades"]
        assert [trade["side"] for trade in trades[:2]] == ["BUY", "SELL"]
        assert trades[0]["amount"] <= 10_000
        assert trades[0]["signal_date"][:10] >= start.isoformat()
    assert payload["audit"]["warmup_bars"] == 30
    assert payload["audit"]["warmup_trading_allowed"] is False


def test_csv_loader_rejects_missing_raw_marker_by_default(tmp_path):
    _bars(raw=False).to_csv(tmp_path / "600001.csv", index=False)

    with pytest.raises(ValueError, match="adjustment_type=raw"):
        load_csv_directory(tmp_path)


def test_adjusted_research_override_adds_explicit_warning(tmp_path):
    _bars(raw=False).to_csv(tmp_path / "600001.csv", index=False)

    bars, audit = load_csv_directory(tmp_path, allow_adjusted_research=True)
    payload = run_dual_strategy_backtest(
        bars,
        data_audit=audit,
        start=Date(2024, 2, 12),
        end=Date(2024, 2, 20),
    )

    assert audit.research_only is True
    assert audit.data_warning
    assert payload["audit"]["research_only"] is True
    assert "不得用于生产" in payload["audit"]["data_warning"]


def test_optimization_keeps_warmup_outside_oos_trading_and_never_selects_on_oos():
    frame = _bars(periods=110)
    report = optimize_dual_strategies(
        {"600001": frame},
        start=Date(2024, 1, 2),
        end=Date(2024, 5, 31),
        walk_forward=WalkForwardConfig(
            start_date=Date(2024, 1, 2),
            end_date=Date(2024, 5, 31),
            train_window_days=45,
            oos_window_days=20,
            purge_days=1,
            step_days=40,
        ),
        account1_candidates=(
            {
                "max_below_ma10_pct": None,
                "require_ma10_above_ma20": False,
                "min_expected_rr": 0.0,
            },
        ),
        account3_candidates=(
            {
                "a_ma20_tolerance": 0.015,
                "b_ma10_tolerance": 0.01,
                "max_volume_ratio": 0.8,
                "min_score": 5,
                "min_expected_rr": 1.2,
            },
        ),
        data_audit=DataAudit(),
    )

    for account in ("account1", "account3"):
        account_report = report["accounts"][account]
        assert account_report["selection_policy"]["oos_used_for_selection"] is False
        for window in account_report["windows"]:
            assert "candidates" in window
            assert "oos_result" in window
            first_signal = window["oos_result"]["metrics"]["first_signal_date"]
            assert first_signal is None or first_signal >= window["oos"]["start"]
    assert report["audit"]["warmup_trading_allowed"] is False
