import json
from datetime import date as Date

import pytest

from research.strategy_optimization import (
    NestedWalkForwardEvaluator,
    StrategyOptimizationConfig,
)
from research.walk_forward import WalkForwardConfig


def _config(*, holdout: bool = True, penalty: float = 1.0) -> StrategyOptimizationConfig:
    return StrategyOptimizationConfig(
        walk_forward=WalkForwardConfig(
            start_date=Date(2024, 1, 1),
            end_date=Date(2024, 2, 5),
            train_window_days=10,
            oos_window_days=5,
            purge_days=1,
            step_days=10,
            holdout_start=Date(2024, 2, 1) if holdout else None,
            holdout_end=Date(2024, 2, 5) if holdout else None,
        ),
        min_trades=30,
        small_sample_penalty=penalty,
    )


def test_oos_only_receives_training_selected_params_and_cannot_select():
    calls = []
    objective_kinds = []

    def backtest(window, params):
        calls.append((window.kind, window.split_index, params["lookback"]))
        # 如果 OOS 能反向选参，lookback=20 会以极高 OOS 结果胜出；但它不应被 OOS 调用。
        gross = params["lookback"] / 10 if window.kind == "train" else 100.0
        return {"gross_expectancy": gross, "cost_per_trade": 0.1, "num_trades": 50}

    def objective(result):
        objective_kinds.append(result["metrics"]["gross_expectancy"])
        return result["cost_results"]["1x"]["net_expectancy"]

    evaluator = NestedWalkForwardEvaluator(
        _config(),
        [{"lookback": 10}, {"lookback": 20}],
        backtest,
        objective_fn=objective,
    )
    report = evaluator.evaluate(data_hash="data-v1", code_hash="code-v1")

    oos_calls = [call for call in calls if call[0] == "oos"]
    assert oos_calls == [("oos", 0, 20), ("oos", 1, 20)]
    assert len(objective_kinds) == 4  # 仅 2窗口 × 2训练候选，OOS/holdout 不进入目标函数
    assert report.final_best_params == {"lookback": 20}
    assert report.selection_policy["oos_used_for_selection"] is False
    assert report.num_attempts == 7


def test_cost_scenarios_are_derived_from_one_backtest_attempt():
    calls = []

    def backtest(window, params):
        calls.append((window.kind, params["name"]))
        return {"gross_expectancy": 1.2, "cost_per_trade": 0.2, "num_trades": 40}

    report = NestedWalkForwardEvaluator(
        _config(holdout=False),
        [{"name": "only"}],
        backtest,
    ).evaluate(data_hash="d", code_hash="c")

    result = report.windows[0]["candidates"][0]["result"]
    assert result["cost_results"] == {
        "baseline": {"cost_multiplier": 0.0, "net_expectancy": 1.2},
        "1x": {"cost_multiplier": 1.0, "net_expectancy": 1.0},
        "2x": {"cost_multiplier": 2.0, "net_expectancy": 0.7999999999999999},
    }
    assert len(calls) == report.num_attempts


def test_default_ranking_penalizes_small_samples_after_costs():
    def backtest(window, params):
        if params["name"] == "tiny":
            return {"gross_expectancy": 1.1, "cost_per_trade": 0.1, "num_trades": 1}
        return {"gross_expectancy": 0.6, "cost_per_trade": 0.1, "num_trades": 30}

    report = NestedWalkForwardEvaluator(
        _config(holdout=False),
        [{"name": "tiny"}, {"name": "credible"}],
        backtest,
    ).evaluate(data_hash="d", code_hash="c")

    assert all(window["best_params"] == {"name": "credible"} for window in report.windows)
    assert report.candidate_ranking[0]["params"] == {"name": "credible"}


def test_holdout_is_attempted_once_and_uses_training_only_final_params():
    calls = []

    def backtest(window, params):
        calls.append(window.kind)
        return {
            "gross_expectancy": 1.0 if params["p"] == 1 else 0.0,
            "cost_per_trade": 0.0,
            "num_trades": 50,
        }

    evaluator = NestedWalkForwardEvaluator(_config(), [{"p": 1}, {"p": 2}], backtest)
    report = evaluator.evaluate(data_hash="d", code_hash="c")

    assert calls.count("holdout") == 1
    assert report.holdout["params"] == {"p": 1}
    calls_before_retry = list(calls)
    with pytest.raises(RuntimeError, match="already been consumed"):
        evaluator.evaluate(data_hash="d", code_hash="c")
    assert calls == calls_before_retry


def test_report_records_all_candidates_windows_hashes_and_is_json_serializable():
    def backtest(window, params):
        return {
            "gross_expectancy": float(params["p"]),
            "cost_per_trade": 0.05,
            "num_trades": 35,
            "period_end": window.end,
        }

    report = NestedWalkForwardEvaluator(
        _config(holdout=False),
        [{"p": 1}, {"p": 2}],
        backtest,
    ).evaluate(data_hash="data-hash", config_hash="config-hash", code_hash="code-hash")
    payload = json.loads(report.to_json())

    assert payload["data_hash"] == "data-hash"
    assert payload["config_hash"] == "config-hash"
    assert payload["code_hash"] == "code-hash"
    assert payload["all_candidates"] == [{"p": 1}, {"p": 2}]
    assert len(payload["windows"]) == 2
    assert all(len(window["candidates"]) == 2 for window in payload["windows"])
    assert payload["num_attempts"] == 6
    assert payload["windows"][0]["candidates"][0]["result"]["metrics"]["period_end"] == "2024-01-11"
