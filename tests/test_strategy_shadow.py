"""策略 shadow 对照的差异与只读契约测试。"""

import json

import pytest

from research.strategy_shadow import compare_backtest_payloads, load_candidate_params


def _account(trades, *, total_trades, total_return, max_drawdown, net_expectancy):
    return {
        "trades": trades,
        "metrics": {
            "total_trades": total_trades,
            "total_return": total_return,
            "max_drawdown": max_drawdown,
            "net_expectancy": net_expectancy,
        },
    }


def _buy(signal_date, symbol):
    return {"side": "BUY", "signal_date": signal_date, "symbol": symbol}


def test_shadow_detects_added_removed_and_unchanged_buy_signals():
    baseline = {
        "accounts": {
            "account1": _account(
                [_buy("2026-07-01T00:00:00.000", "600001"), _buy("2026-07-02", "600002")],
                total_trades=3,
                total_return=0.01,
                max_drawdown=0.02,
                net_expectancy=12.0,
            ),
            "account3": _account(
                [_buy("2026-07-03", "600003")],
                total_trades=1,
                total_return=0.0,
                max_drawdown=0.0,
                net_expectancy=0.0,
            ),
        },
        "audit": {"research_only": False},
    }
    candidate = {
        "accounts": {
            "account1": _account(
                [_buy("2026-07-01", "600001"), _buy("2026-07-04", "600004")],
                total_trades=4,
                total_return=0.03,
                max_drawdown=0.01,
                net_expectancy=20.0,
            ),
            "account3": baseline["accounts"]["account3"],
        },
        "audit": {"research_only": False},
    }

    result = compare_backtest_payloads(
        baseline,
        candidate,
        candidate_params={"account1": {"min_expected_rr": 1.0}, "account3": {}},
    )

    signals = result["accounts"]["account1"]["buy_signals"]
    assert signals["added"] == [{"signal_date": "2026-07-04", "symbol": "600004"}]
    assert signals["removed"] == [{"signal_date": "2026-07-02", "symbol": "600002"}]
    assert signals["unchanged"] == [{"signal_date": "2026-07-01", "symbol": "600001"}]
    assert result["accounts"]["account1"]["metrics"]["total_trades"] == {
        "baseline": 3,
        "candidate": 4,
        "delta": 1,
    }
    assert result["accounts"]["account1"]["metrics"]["net_expectancy"]["delta"] == 8.0


def test_shadow_result_has_explicit_read_only_production_safety_markers():
    empty = _account(
        [],
        total_trades=0,
        total_return=0.0,
        max_drawdown=0.0,
        net_expectancy=0.0,
    )
    payload = {"accounts": {"account1": empty, "account3": empty}, "audit": {"research_only": True}}

    result = compare_backtest_payloads(
        payload,
        payload,
        candidate_params={"account1": {}, "account3": {}},
    )

    assert result["read_only"] is True
    assert result["changes_production"] is False
    assert result["audit"]["read_only"] is True
    assert result["audit"]["changes_production"] is False
    assert result["audit"]["configuration_written"] is False
    assert result["audit"]["database_written"] is False
    assert result["audit"]["orders_submitted"] is False
    assert result["audit"]["data"]["research_only"] is True


def test_candidate_params_support_optimize_report_and_explicit_json(tmp_path):
    optimize = tmp_path / "optimize.json"
    optimize.write_text(
        json.dumps(
            {
                "accounts": {
                    "account1": {"final_best_params": {"min_expected_rr": 1.0}},
                    "account3": {"final_best_params": {"min_score": 7}},
                }
            }
        ),
        encoding="utf-8",
    )
    explicit = tmp_path / "params.json"
    explicit.write_text(
        json.dumps({"account1": {"min_expected_rr": 1.2}, "account3": {"min_score": 8}}),
        encoding="utf-8",
    )

    assert load_candidate_params(optimize, optimize_report=True)["account3"] == {"min_score": 7}
    assert load_candidate_params(explicit)["account1"] == {"min_expected_rr": 1.2}
    with pytest.raises(ValueError, match="--optimize-json"):
        load_candidate_params(optimize)
