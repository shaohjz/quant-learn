"""双账户策略参数的只读 shadow 对照。

本模块只复用研究回测器读取传入的行情并生成内存结果，不读取或写入配置、
数据库、生产信号，也不调用任何下单接口。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date as Date
from pathlib import Path
from typing import Any

import pandas as pd

from research.dual_strategy_backtest import DataAudit, run_dual_strategy_backtest
from research.portfolio_backtest import BacktestConfig

ACCOUNT_NAMES = ("account1", "account3")
METRIC_NAMES = ("total_trades", "total_return", "max_drawdown", "net_expectancy")


def load_candidate_params(
    path: str | Path,
    *,
    optimize_report: bool = False,
) -> dict[str, dict[str, Any]]:
    """从显式参数 JSON 或 optimize 报告读取两账户候选参数。"""

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取候选参数 JSON: {source}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise TypeError("候选参数 JSON 顶层必须是对象")

    accounts = payload.get("accounts", payload)
    if not isinstance(accounts, Mapping):
        raise TypeError("候选参数 JSON 的 accounts 必须是对象")

    resolved: dict[str, dict[str, Any]] = {}
    for account in ACCOUNT_NAMES:
        entry = accounts.get(account)
        if not isinstance(entry, Mapping):
            raise TypeError(f"候选参数 JSON 缺少对象 {account}")
        if optimize_report:
            entry = entry.get("final_best_params")
            if not isinstance(entry, Mapping):
                raise ValueError(f"optimize JSON 缺少 {account}.final_best_params")
        elif "final_best_params" in entry:
            raise ValueError("检测到 optimize 报告；请改用 --optimize-json")
        resolved[account] = dict(entry)
    return resolved


def compare_strategy_shadow(
    bars_by_symbol: Mapping[str, pd.DataFrame],
    *,
    start: Date,
    end: Date,
    candidate_params: Mapping[str, Mapping[str, Any]],
    backtest_config: BacktestConfig | None = None,
    data_audit: DataAudit | None = None,
    candidate_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """在完全相同的数据、日期和执行参数上比较 baseline 与候选参数。"""

    if end < start:
        raise ValueError("end 不能早于 start")
    missing = [account for account in ACCOUNT_NAMES if account not in candidate_params]
    if missing:
        raise ValueError(f"候选参数缺少账户: {missing}")

    baseline = run_dual_strategy_backtest(
        bars_by_symbol,
        start=start,
        end=end,
        backtest_config=backtest_config,
        data_audit=data_audit,
    )
    candidate = run_dual_strategy_backtest(
        bars_by_symbol,
        start=start,
        end=end,
        account1_params=candidate_params["account1"],
        account3_params=candidate_params["account3"],
        backtest_config=backtest_config,
        data_audit=data_audit,
    )
    return compare_backtest_payloads(
        baseline,
        candidate,
        candidate_params=candidate_params,
        candidate_source=candidate_source,
    )


def compare_backtest_payloads(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    candidate_params: Mapping[str, Mapping[str, Any]],
    candidate_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """比较两份 dual strategy 结果；分离出来便于审计和差异单测。"""

    baseline_accounts = _accounts(baseline, "baseline")
    candidate_accounts = _accounts(candidate, "candidate")
    accounts: dict[str, Any] = {}
    for account in ACCOUNT_NAMES:
        accounts[account] = _compare_account(
            _account_result(baseline_accounts, account, "baseline"),
            _account_result(candidate_accounts, account, "candidate"),
        )

    return {
        "mode": "strategy_shadow_compare",
        "read_only": True,
        "changes_production": False,
        "candidate_source": dict(candidate_source or {}),
        "candidate_params": {account: dict(candidate_params[account]) for account in ACCOUNT_NAMES},
        "accounts": accounts,
        "audit": {
            "read_only": True,
            "changes_production": False,
            "configuration_written": False,
            "database_written": False,
            "orders_submitted": False,
            "data": dict(candidate.get("audit", baseline.get("audit", {}))),
        },
    }


def _compare_account(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_signals = _buy_signal_set(baseline)
    candidate_signals = _buy_signal_set(candidate)
    baseline_metrics = _metrics(baseline)
    candidate_metrics = _metrics(candidate)

    metric_comparison = {}
    for name in METRIC_NAMES:
        before = baseline_metrics.get(name, 0)
        after = candidate_metrics.get(name, 0)
        metric_comparison[name] = {
            "baseline": before,
            "candidate": after,
            "delta": after - before,
        }

    return {
        "buy_signals": {
            "baseline_count": len(baseline_signals),
            "candidate_count": len(candidate_signals),
            "added": _signal_records(candidate_signals - baseline_signals),
            "removed": _signal_records(baseline_signals - candidate_signals),
            "unchanged": _signal_records(baseline_signals & candidate_signals),
        },
        "metrics": metric_comparison,
    }


def _buy_signal_set(result: Mapping[str, Any]) -> set[tuple[str, str]]:
    signals: set[tuple[str, str]] = set()
    trades = result.get("trades", [])
    if not isinstance(trades, list):
        raise TypeError("账户回测结果 trades 必须是数组")
    for trade in trades:
        if isinstance(trade, Mapping) and trade.get("side") == "BUY":
            signals.add((str(trade.get("signal_date", ""))[:10], str(trade.get("symbol", ""))))
    return signals


def _signal_records(signals: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"signal_date": signal_date, "symbol": symbol} for signal_date, symbol in sorted(signals)]


def _accounts(payload: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    accounts = payload.get("accounts")
    if not isinstance(accounts, Mapping):
        raise TypeError(f"{label} 回测结果缺少 accounts")
    return accounts


def _account_result(accounts: Mapping[str, Any], account: str, label: str) -> Mapping[str, Any]:
    result = accounts.get(account)
    if not isinstance(result, Mapping):
        raise TypeError(f"{label} 回测结果缺少 {account}")
    return result


def _metrics(result: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = result.get("metrics")
    if not isinstance(metrics, Mapping):
        raise TypeError("账户回测结果缺少 metrics")
    return metrics
