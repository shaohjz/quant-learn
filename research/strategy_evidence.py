"""只读交易记录并生成策略晋级证据。

本模块不导入 ``sim.db``，调用方可以传入交易记录，或显式指定 SQLite
连接。闭环交易复用 ``sim.signal_performance`` 的 FIFO 实现。
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from research.promotion_gate import PromotionEvidence, PromotionGate
from sim.signal_performance import build_signal_segments

ACCOUNT_STRATEGIES: dict[int, tuple[str, ...]] = {
    1: ("buy_zone",),
    3: ("A", "B"),
}
DOMINANCE_THRESHOLD = 0.5
BACKTEST_ACCOUNTS = {1: "account1", 3: "account3"}
MISSING_BACKTEST_REASON = "缺少 dual optimize 回测报告"


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _iso_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_strategy_reason(reason: Any, account_id: int) -> str | None:
    """从买单原因解析本任务关心的策略标签。

    account 1 只认 ``buy_zone``；account 3 只认波段原因中的 ``A类`` /
    ``B类``（同时兼容 ``|A|``、``strategy=A`` 形式）。
    """
    text = str(reason or "").strip()
    if account_id == 1:
        return "buy_zone" if re.search(r"(?<![A-Za-z0-9_])buy_zone(?![A-Za-z0-9_])", text, re.IGNORECASE) else None
    if account_id != 3:
        return None

    match = re.search(
        r"(?:波段(?:信号)?\s*[|:：-]?\s*|strategy\s*[=:]\s*|\|)\s*([AB])\s*(?:类|\||\b)",
        text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(r"(?:^|[\s|:：,，;；])([AB])\s*类?(?=$|[\s|:：,，;；])", text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def read_trade_records(
    db_path: str | Path,
    *,
    account_ids: Iterable[int] = (1, 3),
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """以 SQLite 只读模式读取交易记录，绝不创建或修改数据库。"""
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"SQLite 数据库不存在: {path}")

    ids = tuple(dict.fromkeys(int(value) for value in account_ids))
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    sql = f"SELECT * FROM sim_trades WHERE account_id IN ({placeholders})"
    params: list[Any] = list(ids)
    if as_of is not None:
        sql += " AND trade_date <= ?"
        params.append(as_of.isoformat())
    sql += " ORDER BY trade_date, id"

    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    except sqlite3.Error as exc:
        raise RuntimeError(f"读取 SQLite 交易记录失败: {exc}") from exc
    finally:
        conn.close()


def load_optimization_report(path: str | Path) -> dict[str, Any]:
    """读取 dual optimize JSON；不会改动报告文件。"""
    report_path = Path(path).expanduser().resolve()
    if not report_path.is_file():
        raise FileNotFoundError(f"优化报告不存在: {report_path}")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"优化报告不是有效 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError("优化报告根节点必须是 JSON 对象")
    return payload


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"优化报告缺少对象字段: {field}")
    return value


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"优化报告缺少非空字段: {field}")
    return value


def _finite_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"优化报告字段必须是数值: {field}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"优化报告字段必须是有限数值: {field}")
    return result


def extract_backtest_evidence(report: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    """从 dual optimize 报告提取 OOS 证据，并验证 OOS 不参与选参。"""
    if report.get("mode") != "optimize":
        raise ValueError("优化报告 mode 必须为 optimize")
    accounts = _required_mapping(report.get("accounts"), "accounts")
    extracted: dict[int, dict[str, Any]] = {}

    for account_id, account_name in BACKTEST_ACCOUNTS.items():
        account = _required_mapping(accounts.get(account_name), f"accounts.{account_name}")
        policy = _required_mapping(
            account.get("selection_policy"),
            f"accounts.{account_name}.selection_policy",
        )
        if policy.get("oos_used_for_selection") is not False:
            raise ValueError(f"{account_name} 未明确声明 OOS 不参与选参")
        if policy.get("source") != "training_windows_only":
            raise ValueError(f"{account_name} 选参来源必须为 training_windows_only")

        data_hash = _required_text(account.get("data_hash"), f"{account_name}.data_hash")
        config_hash = _required_text(account.get("config_hash"), f"{account_name}.config_hash")
        final_params = _required_mapping(
            account.get("final_best_params"),
            f"{account_name}.final_best_params",
        )
        windows = account.get("windows")
        if not isinstance(windows, list) or not windows:
            raise ValueError(f"{account_name} 缺少 OOS 窗口")

        oos_windows: list[dict[str, Any]] = []
        for index, window_value in enumerate(windows):
            window = _required_mapping(window_value, f"{account_name}.windows[{index}]")
            oos = _required_mapping(window.get("oos"), f"{account_name}.windows[{index}].oos")
            oos_result = _required_mapping(
                window.get("oos_result"),
                f"{account_name}.windows[{index}].oos_result",
            )
            cost_results = _required_mapping(
                oos_result.get("cost_results"),
                f"{account_name}.windows[{index}].oos_result.cost_results",
            )
            doubled = _required_mapping(
                cost_results.get("2x"),
                f"{account_name}.windows[{index}].oos_result.cost_results.2x",
            )
            expectancy = _finite_float(
                doubled.get("net_expectancy"),
                f"{account_name}.windows[{index}].oos_result.cost_results.2x.net_expectancy",
            )
            oos_windows.append(
                {
                    "split_index": window.get("split_index", index),
                    "start": oos.get("start"),
                    "end": oos.get("end"),
                    "net_expectancy_2x_cost": expectancy,
                }
            )

        values = [row["net_expectancy_2x_cost"] for row in oos_windows]
        extracted[account_id] = {
            "available": True,
            "account": account_name,
            "data_hash": data_hash,
            "config_hash": config_hash,
            "final_params": dict(final_params),
            "oos_windows": oos_windows,
            "oos_net_expectancy_2x_cost_mean": sum(values) / len(values),
            "oos_positive_windows_pct": sum(value > 0 for value in values) / len(values),
            "selection_policy": dict(policy),
        }
    return extracted


def _missing_backtest_evidence(account_id: int) -> dict[str, Any]:
    return {
        "available": False,
        "account": BACKTEST_ACCOUNTS[account_id],
        "reason": MISSING_BACKTEST_REASON,
        "data_hash": None,
        "config_hash": None,
        "final_params": None,
        "oos_windows": [],
        "oos_net_expectancy_2x_cost_mean": None,
        "oos_positive_windows_pct": None,
    }


def _labeled_rows(trades: Iterable[Any], account_id: int, *, fee_multiplier: float = 1.0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in trades:
        if int(_number(_get(source, "account_id"))) != account_id:
            continue
        row = dict(source)
        row["commission"] = _number(_get(source, "commission")) * fee_multiplier
        row["tax"] = _number(_get(source, "tax")) * fee_multiplier
        if str(_get(source, "direction", "")).upper() == "BUY":
            reason = _get(source, "signal_reason") or _get(source, "reason")
            label = parse_strategy_reason(reason, account_id)
            # signal_performance 优先读取结构化标签。未识别原因也显式隔离，
            # 避免其通用标准化规则把普通文本误归到本任务的 A/B。
            row["signal_detail"] = {"trigger_type": label or "__other__"}
        rows.append(row)
    return rows


def _holding_days(segment: dict[str, Any]) -> int:
    opened = _iso_date(segment.get("buy_date"))
    closed = _iso_date(segment.get("close_date"))
    if opened is None or closed is None:
        return 0
    return max((closed - opened).days, 0)


def _strategy_metrics(
    label: str,
    segments: list[dict[str, Any]],
    stressed_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = [segment for segment in segments if segment.get("signal") == label]
    stressed = [segment for segment in stressed_segments if segment.get("signal") == label]
    pnls = [_number(segment.get("pnl")) for segment in selected]
    profits = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_profit = sum(profits)
    gross_loss = abs(sum(losses))

    by_stock: dict[str, float] = {}
    for segment in selected:
        code = str(segment.get("stock_code") or "unknown")
        by_stock[code] = by_stock.get(code, 0.0) + _number(segment.get("pnl"))
    absolute_contribution = sum(abs(value) for value in by_stock.values())
    concentration = (
        max((abs(value) for value in by_stock.values()), default=0.0) / absolute_contribution
        if absolute_contribution
        else 0.0
    )

    trade_dates = {
        parsed
        for segment in selected
        for parsed in (_iso_date(segment.get("buy_date")), _iso_date(segment.get("close_date")))
        if parsed is not None
    }
    count = len(selected)
    return {
        "strategy": label,
        "closed_trades": count,
        "wins": len(profits),
        "losses": len(losses),
        "fee_adjusted_win_rate": len(profits) / count if count else 0.0,
        "average_profit": sum(profits) / len(profits) if profits else 0.0,
        "average_loss": sum(losses) / len(losses) if losses else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "net_pnl": sum(pnls),
        "net_expectancy": sum(pnls) / count if count else 0.0,
        "net_expectancy_2x_cost": (
            sum(_number(segment.get("pnl")) for segment in stressed) / len(stressed) if stressed else 0.0
        ),
        "average_holding_days": (sum(_holding_days(segment) for segment in selected) / count if count else 0.0),
        "single_stock_contribution_concentration": concentration,
        "single_stock_dominance": concentration > DOMINANCE_THRESHOLD,
        "paper_trading_days": len(trade_dates),
        "stock_contributions": dict(sorted(by_stock.items())),
    }


def _evaluate_metrics(
    metrics: dict[str, Any],
    backtest_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    available = backtest_evidence.get("available") is True
    backtest_expectancy = backtest_evidence.get("oos_net_expectancy_2x_cost_mean")
    conservative_expectancy = min(float(backtest_expectancy), metrics["net_expectancy_2x_cost"]) if available else 0.0
    evidence = PromotionEvidence(
        strategy_name=metrics["strategy"],
        data_hash=str(backtest_evidence.get("data_hash") or ""),
        config_hash=str(backtest_evidence.get("config_hash") or ""),
        num_closed_trades=metrics["closed_trades"],
        oos_positive_windows_pct=(float(backtest_evidence["oos_positive_windows_pct"]) if available else 0.0),
        net_expectancy_2x_cost=conservative_expectancy,
        single_stock_dominance=metrics["single_stock_dominance"],
        paper_trading_days=metrics["paper_trading_days"],
    )
    evaluated = asdict(PromotionGate().evaluate(evidence))
    if not available:
        # 缺报告时用 null 明示证据未知；上面的 0 只用于安全执行现有 Gate。
        evaluated["data_hash"] = None
        evaluated["config_hash"] = None
        evaluated["oos_positive_windows_pct"] = None
        evaluated["net_expectancy_2x_cost"] = None
        evaluated["block_reasons"] = [
            reason
            for reason in evaluated["block_reasons"]
            if not reason.startswith(("OOS正超额窗口不足", "2倍成本压力下净期望"))
        ]
        evaluated["block_reasons"].append(MISSING_BACKTEST_REASON)
        evaluated["can_promote"] = False
    return evaluated


def summarize_account(
    trades: Iterable[Any],
    account_id: int,
    *,
    backtest_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """汇总单账户策略指标并执行 PromotionGate。"""
    source = list(trades)
    resolved_backtest = backtest_evidence or _missing_backtest_evidence(account_id)
    normal = build_signal_segments(_labeled_rows(source, account_id))
    stressed = build_signal_segments(_labeled_rows(source, account_id, fee_multiplier=2.0))
    strategy_rows = []
    for label in ACCOUNT_STRATEGIES.get(account_id, ()):
        metrics = _strategy_metrics(label, normal, stressed)
        strategy_rows.append(
            {
                **metrics,
                "backtest_evidence": dict(resolved_backtest),
                "promotion_evidence": _evaluate_metrics(metrics, resolved_backtest),
            }
        )
    return {
        "account_id": account_id,
        "backtest_evidence": dict(resolved_backtest),
        "strategies": strategy_rows,
        "closed_trades": sum(row["closed_trades"] for row in strategy_rows),
        "paper_trading_days": len(
            {
                parsed
                for row in source
                if int(_number(_get(row, "account_id"))) == account_id
                for parsed in (_iso_date(_get(row, "trade_date")),)
                if parsed is not None
            }
        ),
    }


def build_strategy_evidence(
    trades: Iterable[Any],
    *,
    as_of: date | None = None,
    optimization_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """从可注入交易记录构造两个账户的机器可读证据报告。"""
    cutoff = as_of or datetime.now().astimezone().date()
    backtests = (
        extract_backtest_evidence(optimization_report)
        if optimization_report is not None
        else {account_id: _missing_backtest_evidence(account_id) for account_id in ACCOUNT_STRATEGIES}
    )
    filtered = [
        row
        for row in trades
        if (_iso_date(_get(row, "trade_date")) is None or _iso_date(_get(row, "trade_date")) <= cutoff)
    ]
    return {
        "as_of": cutoff.isoformat(),
        "read_only": True,
        "accounts": {
            str(account_id): summarize_account(
                filtered,
                account_id,
                backtest_evidence=backtests[account_id],
            )
            for account_id in ACCOUNT_STRATEGIES
        },
    }


# 便于研究代码使用的明确别名。
analyze_strategy_evidence = build_strategy_evidence
