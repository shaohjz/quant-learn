"""通用嵌套滚动参数评估器。

参数只允许在训练窗口内选择；OOS 仅评估已冻结参数。最终 holdout
使用所有训练窗口汇总出的参数，并且每个评估器实例最多尝试一次。

注入的 ``backtest_fn`` 签名为 ``(window, params) -> metrics``。metrics
至少应包含 ``gross_expectancy``、``cost_per_trade`` 和 ``num_trades``。
评估器会由单次回测派生 baseline、1x、2x 成本结果，因此不会为成本
情景重复运行 holdout。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date as Date
from typing import Any

from research.walk_forward import (
    WalkForwardConfig,
    WalkForwardSplit,
    generate_walk_forward_splits,
    validate_no_oos_leakage,
)

BacktestFn = Callable[["EvaluationWindow", Mapping[str, Any]], Mapping[str, Any]]
ObjectiveFn = Callable[[Mapping[str, Any]], float]


@dataclass(frozen=True)
class EvaluationWindow:
    """只暴露当前阶段边界，避免评估器把 OOS 数据交给训练选参。"""

    kind: str
    start: Date
    end: Date
    split_index: int | None = None


@dataclass
class StrategyOptimizationConfig:
    """评估配置。"""

    walk_forward: WalkForwardConfig
    min_trades: int = 30
    small_sample_penalty: float = 1.0
    cost_multipliers: tuple[float, ...] = (0.0, 1.0, 2.0)

    def __post_init__(self) -> None:
        if self.min_trades <= 0:
            raise ValueError("min_trades must be positive")
        if self.small_sample_penalty < 0:
            raise ValueError("small_sample_penalty cannot be negative")
        if self.cost_multipliers != (0.0, 1.0, 2.0):
            raise ValueError("cost_multipliers must be exactly baseline, 1x and 2x")


@dataclass
class StrategyOptimizationReport:
    """完整且可 JSON 序列化的审计报告。"""

    data_hash: str
    config_hash: str
    code_hash: str
    num_attempts: int
    all_candidates: list[dict[str, Any]]
    windows: list[dict[str, Any]]
    final_best_params: dict[str, Any]
    candidate_ranking: list[dict[str, Any]]
    holdout: dict[str, Any] | None
    selection_policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=indent,
            allow_nan=False,
        )


class NestedWalkForwardEvaluator:
    """训练选参、OOS 盲评、最终 holdout 一次性评估。"""

    def __init__(
        self,
        config: StrategyOptimizationConfig,
        candidates: Sequence[Mapping[str, Any]],
        backtest_fn: BacktestFn,
        objective_fn: ObjectiveFn | None = None,
    ):
        if not candidates:
            raise ValueError("at least one candidate is required")
        if config.walk_forward.allow_oos_param_selection:
            raise ValueError("OOS parameter selection is forbidden")

        self._config = config
        self._candidates = [_canonical_params(candidate) for candidate in candidates]
        if len({_stable_json(candidate) for candidate in self._candidates}) != len(self._candidates):
            raise ValueError("candidates must be unique")
        self._backtest_fn = backtest_fn
        self._objective_fn = objective_fn or self._default_objective
        self._holdout_consumed = False

    def evaluate(
        self,
        *,
        data_hash: str,
        code_hash: str,
        config_hash: str | None = None,
        include_holdout: bool = True,
    ) -> StrategyOptimizationReport:
        """运行嵌套滚动评估并返回完整报告。

        OOS 结果不会传给目标函数，也不会参与最终参数排序。最终排序仅
        汇总各训练窗口分数；holdout 参数在调用 holdout 前即已冻结。
        """

        self._validate_hash("data_hash", data_hash)
        self._validate_hash("code_hash", code_hash)
        resolved_config_hash = config_hash or self._compute_config_hash()
        self._validate_hash("config_hash", resolved_config_hash)
        if include_holdout and self._has_holdout() and self._holdout_consumed:
            raise RuntimeError("final holdout has already been consumed")

        splits = self._splits()
        attempts = 0
        windows: list[dict[str, Any]] = []
        aggregate_scores: dict[str, list[float]] = {_stable_json(candidate): [] for candidate in self._candidates}

        for split_index, split in enumerate(splits):
            train_window = EvaluationWindow(
                kind="train",
                start=split.train_start,
                end=split.train_end,
                split_index=split_index,
            )
            training_results: list[dict[str, Any]] = []
            for candidate in self._candidates:
                result = self._run_once(train_window, candidate)
                attempts += 1
                score = self._score(result)
                aggregate_scores[_stable_json(candidate)].append(score)
                training_results.append(
                    {
                        "params": candidate,
                        "result": result,
                        "selection_score": score,
                    }
                )

            best = max(
                training_results,
                key=lambda item: (item["selection_score"], _stable_json(item["params"])),
            )
            frozen_params = dict(best["params"])
            oos_window = EvaluationWindow(
                kind="oos",
                start=split.oos_start,
                end=split.oos_end,
                split_index=split_index,
            )
            oos_result = self._run_once(oos_window, frozen_params)
            attempts += 1
            windows.append(
                {
                    "split_index": split_index,
                    "train": _window_dict(train_window),
                    "oos": _window_dict(oos_window),
                    "candidates": training_results,
                    "best_params": frozen_params,
                    "best_training_score": best["selection_score"],
                    "oos_result": oos_result,
                }
            )

        ranking = self._training_only_ranking(aggregate_scores)
        final_best_params = dict(ranking[0]["params"])
        holdout_result: dict[str, Any] | None = None

        if include_holdout and self._has_holdout():
            self._holdout_consumed = True
            holdout_window = EvaluationWindow(
                kind="holdout",
                start=self._config.walk_forward.holdout_start,  # type: ignore[arg-type]
                end=self._config.walk_forward.holdout_end,  # type: ignore[arg-type]
            )
            result = self._run_once(holdout_window, final_best_params)
            attempts += 1
            holdout_result = {
                "window": _window_dict(holdout_window),
                "params": final_best_params,
                "result": result,
            }

        return StrategyOptimizationReport(
            data_hash=data_hash,
            config_hash=resolved_config_hash,
            code_hash=code_hash,
            num_attempts=attempts,
            all_candidates=[dict(candidate) for candidate in self._candidates],
            windows=windows,
            final_best_params=final_best_params,
            candidate_ranking=ranking,
            holdout=holdout_result,
            selection_policy={
                "source": "training_windows_only",
                "default_primary_metric": "net_expectancy_1x_cost",
                "small_sample_penalty": self._config.small_sample_penalty,
                "min_trades": self._config.min_trades,
                "oos_used_for_selection": False,
                "holdout_max_attempts": 1,
            },
        )

    def _splits(self) -> list[WalkForwardSplit]:
        cfg = self._config.walk_forward
        splits = generate_walk_forward_splits(
            start_date=cfg.start_date,
            end_date=cfg.end_date,
            train_window_days=cfg.train_window_days,
            oos_window_days=cfg.oos_window_days,
            purge_days=cfg.purge_days,
            embargo_days=cfg.embargo_days,
            step_days=cfg.step_days,
        )
        violations = validate_no_oos_leakage(splits, cfg.holdout_start)
        if violations:
            raise ValueError("; ".join(violations))
        if not splits:
            raise ValueError("walk-forward configuration produced no splits")
        if (cfg.holdout_start is None) != (cfg.holdout_end is None):
            raise ValueError("holdout_start and holdout_end must be set together")
        if cfg.holdout_start and cfg.holdout_end and cfg.holdout_end < cfg.holdout_start:
            raise ValueError("holdout_end cannot precede holdout_start")
        return splits

    def _run_once(
        self,
        window: EvaluationWindow,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        raw = dict(self._backtest_fn(window, dict(params)))
        gross = _finite_number(raw.get("gross_expectancy"), "gross_expectancy")
        cost = _finite_number(raw.get("cost_per_trade"), "cost_per_trade")
        trades = _nonnegative_int(raw.get("num_trades"), "num_trades")
        if cost < 0:
            raise ValueError("cost_per_trade cannot be negative")

        costs = {
            _cost_label(multiplier): {
                "cost_multiplier": multiplier,
                "net_expectancy": gross - multiplier * cost,
            }
            for multiplier in self._config.cost_multipliers
        }
        return {
            "metrics": _json_safe(raw),
            "cost_results": costs,
            "num_trades": trades,
        }

    def _score(self, result: Mapping[str, Any]) -> float:
        score = float(self._objective_fn(result))
        if not math.isfinite(score):
            raise ValueError("objective_fn must return a finite number")
        return score

    def _default_objective(self, result: Mapping[str, Any]) -> float:
        net_expectancy = float(result["cost_results"]["1x"]["net_expectancy"])
        num_trades = int(result["num_trades"])
        shortfall = max(0.0, (self._config.min_trades - num_trades) / self._config.min_trades)
        return net_expectancy - self._config.small_sample_penalty * shortfall

    def _training_only_ranking(
        self,
        aggregate_scores: Mapping[str, list[float]],
    ) -> list[dict[str, Any]]:
        rows = []
        for candidate in self._candidates:
            scores = aggregate_scores[_stable_json(candidate)]
            rows.append(
                {
                    "params": candidate,
                    "mean_training_score": sum(scores) / len(scores),
                    "training_window_scores": scores,
                }
            )
        return sorted(
            rows,
            key=lambda item: (item["mean_training_score"], _stable_json(item["params"])),
            reverse=True,
        )

    def _compute_config_hash(self) -> str:
        payload = _json_safe(asdict(self._config))
        return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()[:16]

    def _has_holdout(self) -> bool:
        cfg = self._config.walk_forward
        return cfg.holdout_start is not None and cfg.holdout_end is not None

    @staticmethod
    def _validate_hash(name: str, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")


def _canonical_params(params: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(params, Mapping):
        raise TypeError("each candidate must be a mapping")
    candidate = _json_safe(dict(params))
    if not isinstance(candidate, dict):
        raise TypeError("each candidate must serialize to a JSON object")
    _stable_json(candidate)
    return candidate


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _cost_label(multiplier: float) -> str:
    return "baseline" if multiplier == 0.0 else f"{int(multiplier)}x"


def _window_dict(window: EvaluationWindow) -> dict[str, Any]:
    return {
        "kind": window.kind,
        "start": window.start.isoformat(),
        "end": window.end.isoformat(),
        "split_index": window.split_index,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value is not JSON serializable: {type(value).__name__}")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
