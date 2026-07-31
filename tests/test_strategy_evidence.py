from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from research.strategy_evidence import (
    build_strategy_evidence,
    parse_strategy_reason,
    read_trade_records,
)

ROOT = Path(__file__).resolve().parents[1]


def _trade(
    trade_id: int,
    account_id: int,
    trade_date: str,
    code: str,
    direction: str,
    price: float,
    quantity: int,
    reason: str,
    commission: float = 0.0,
    tax: float = 0.0,
) -> dict:
    return {
        "id": trade_id,
        "account_id": account_id,
        "trade_date": trade_date,
        "stock_code": code,
        "stock_name": code,
        "direction": direction,
        "price": price,
        "quantity": quantity,
        "commission": commission,
        "tax": tax,
        "signal_reason": reason,
        "signal_detail": None,
    }


def _records() -> list[dict]:
    return [
        _trade(1, 1, "2026-07-01", "600001", "BUY", 10, 100, "自动: buy_zone | 建仓", 10),
        _trade(2, 1, "2026-07-03", "600001", "SELL", 12, 50, "止盈", 6, 2),
        _trade(3, 1, "2026-07-06", "600001", "SELL", 8, 50, "止损", 4, 2),
        _trade(4, 3, "2026-07-01", "000001", "BUY", 10, 100, "波段信号|A类 score=9", 1),
        _trade(5, 3, "2026-07-04", "000001", "SELL", 11, 100, "止盈", 1, 1),
        _trade(6, 3, "2026-07-02", "000002", "BUY", 20, 50, "波段|B类 score=8", 1),
        _trade(7, 3, "2026-07-07", "000002", "SELL", 18, 50, "止损", 1, 1),
    ]


def _optimization_report() -> dict:
    def account(name: str, values: list[float]) -> dict:
        return {
            "data_hash": f"{name}-data",
            "config_hash": f"{name}-config",
            "final_best_params": {"lookback": 10 if name == "account1" else 20},
            "selection_policy": {
                "source": "training_windows_only",
                "oos_used_for_selection": False,
            },
            "windows": [
                {
                    "split_index": index,
                    "oos": {
                        "kind": "oos",
                        "start": f"2026-0{index + 1}-01",
                        "end": f"2026-0{index + 1}-28",
                    },
                    "best_params": {"lookback": 999},
                    "oos_result": {
                        "cost_results": {
                            "2x": {
                                "cost_multiplier": 2.0,
                                "net_expectancy": value,
                            }
                        }
                    },
                }
                for index, value in enumerate(values)
            ],
        }

    return {
        "mode": "optimize",
        "accounts": {
            "account1": account("account1", [1.0, 3.0]),
            "account3": account("account3", [-2.0, 4.0]),
        },
        "audit": {
            "selection_policy": "training_only; OOS and holdout never select parameters",
        },
    }


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY,
            account_id INTEGER,
            trade_date TEXT,
            stock_code TEXT,
            stock_name TEXT,
            direction TEXT,
            price REAL,
            quantity INTEGER,
            commission REAL,
            tax REAL,
            signal_reason TEXT,
            signal_detail TEXT
        )"""
    )
    conn.executemany(
        """INSERT INTO sim_trades VALUES
           (:id, :account_id, :trade_date, :stock_code, :stock_name, :direction,
            :price, :quantity, :commission, :tax, :signal_reason, :signal_detail)""",
        _records(),
    )
    conn.commit()
    conn.close()


def test_reason_parser_is_account_specific():
    assert parse_strategy_reason("自动: buy_zone | 建仓", 1) == "buy_zone"
    assert parse_strategy_reason("波段信号|A类 score=9", 3) == "A"
    assert parse_strategy_reason("波段|B类 score=8", 3) == "B"
    assert parse_strategy_reason("波段信号|A类", 1) is None
    assert parse_strategy_reason("buy_zone", 3) is None


def test_fifo_fee_adjusted_metrics_and_promotion_evidence():
    report = build_strategy_evidence(_records(), as_of=date(2026, 7, 31))
    account_1 = report["accounts"]["1"]
    buy_zone = account_1["strategies"][0]

    assert account_1["closed_trades"] == 2
    assert buy_zone["fee_adjusted_win_rate"] == pytest.approx(0.5)
    assert buy_zone["average_profit"] == pytest.approx(87.0)
    assert buy_zone["average_loss"] == pytest.approx(-111.0)
    assert buy_zone["profit_factor"] == pytest.approx(87 / 111)
    assert buy_zone["net_expectancy"] == pytest.approx(-12.0)
    assert buy_zone["net_expectancy_2x_cost"] == pytest.approx(-24.0)
    assert buy_zone["average_holding_days"] == pytest.approx(3.5)
    assert buy_zone["single_stock_contribution_concentration"] == pytest.approx(1.0)
    assert buy_zone["paper_trading_days"] == 3
    assert buy_zone["promotion_evidence"]["num_closed_trades"] == 2
    assert buy_zone["promotion_evidence"]["can_promote"] is False

    strategies = {row["strategy"]: row for row in report["accounts"]["3"]["strategies"]}
    assert strategies["A"]["closed_trades"] == 1
    assert strategies["A"]["net_pnl"] == pytest.approx(97.0)
    assert strategies["B"]["closed_trades"] == 1
    assert strategies["B"]["net_pnl"] == pytest.approx(-103.0)


def test_optimization_report_merges_oos_and_paper_evidence_conservatively():
    report = build_strategy_evidence(
        _records(),
        as_of=date(2026, 7, 31),
        optimization_report=_optimization_report(),
    )
    buy_zone = report["accounts"]["1"]["strategies"][0]
    backtest = buy_zone["backtest_evidence"]
    evidence = buy_zone["promotion_evidence"]

    assert [row["net_expectancy_2x_cost"] for row in backtest["oos_windows"]] == [1.0, 3.0]
    assert backtest["oos_net_expectancy_2x_cost_mean"] == pytest.approx(2.0)
    assert backtest["oos_positive_windows_pct"] == pytest.approx(1.0)
    assert backtest["data_hash"] == "account1-data"
    assert backtest["config_hash"] == "account1-config"
    assert backtest["final_params"] == {"lookback": 10}
    assert evidence["data_hash"] == "account1-data"
    assert evidence["config_hash"] == "account1-config"
    assert evidence["oos_positive_windows_pct"] == pytest.approx(1.0)
    # Paper FIFO 为 -24，OOS 均值为 2，晋级只能采用更保守的 -24。
    assert evidence["net_expectancy_2x_cost"] == pytest.approx(-24.0)
    assert "block_reasons" in evidence

    account3 = report["accounts"]["3"]
    assert account3["backtest_evidence"]["oos_positive_windows_pct"] == pytest.approx(0.5)
    strategies = {row["strategy"]: row for row in account3["strategies"]}
    # A 的 Paper 值高于 OOS 均值 1，因此采用 1；B 的 Paper 值更差，因此采用 Paper。
    assert strategies["A"]["promotion_evidence"]["net_expectancy_2x_cost"] == pytest.approx(1.0)
    assert strategies["B"]["promotion_evidence"]["net_expectancy_2x_cost"] == pytest.approx(-106.0)


def test_missing_optimization_report_is_explicit_and_blocks_without_fabrication():
    report = build_strategy_evidence(_records(), as_of=date(2026, 7, 31))
    strategy = report["accounts"]["1"]["strategies"][0]

    assert strategy["backtest_evidence"]["available"] is False
    assert strategy["backtest_evidence"]["oos_net_expectancy_2x_cost_mean"] is None
    assert strategy["promotion_evidence"]["oos_positive_windows_pct"] is None
    assert strategy["promotion_evidence"]["net_expectancy_2x_cost"] is None
    assert strategy["promotion_evidence"]["can_promote"] is False
    assert any("缺少 dual optimize 回测报告" in reason for reason in strategy["promotion_evidence"]["block_reasons"])
    assert not any(
        reason.startswith(("OOS正超额窗口不足", "2倍成本压力下净期望"))
        for reason in strategy["promotion_evidence"]["block_reasons"]
    )


def test_rejects_report_unless_oos_is_explicitly_excluded_from_selection():
    optimization = _optimization_report()
    optimization["accounts"]["account3"]["selection_policy"]["oos_used_for_selection"] = True

    with pytest.raises(ValueError, match="OOS 不参与选参"):
        build_strategy_evidence(
            _records(),
            as_of=date(2026, 7, 31),
            optimization_report=optimization,
        )


def test_sqlite_reader_and_cli_write_only_requested_snapshot(tmp_path):
    db = tmp_path / "trades.db"
    _seed_db(db)
    before = db.read_bytes()

    rows = read_trade_records(db)
    assert {row["account_id"] for row in rows} == {1, 3}
    assert db.read_bytes() == before

    output = tmp_path / "promotion"
    optimization_report = tmp_path / "dual-optimize.json"
    optimization_report.write_text(
        json.dumps(_optimization_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "weekly_strategy_evidence.py"),
            "--db",
            str(db),
            "--output",
            str(output),
            "--optimization-report",
            str(optimization_report),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    files = list(output.iterdir())
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["read_only"] is True
    assert set(payload["accounts"]) == {"1", "3"}
    assert payload["accounts"]["1"]["backtest_evidence"]["available"] is True
    assert db.read_bytes() == before


def test_cli_missing_database_is_clear_and_nonzero(tmp_path):
    output = tmp_path / "promotion"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "weekly_strategy_evidence.py"),
            "--db",
            str(tmp_path / "missing.db"),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "SQLite 数据库不存在" in result.stderr
    assert not output.exists()
