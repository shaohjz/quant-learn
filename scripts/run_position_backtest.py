#!/usr/bin/env python3
"""跑中长线参数网格，并对照旧 MA10/MA20 策略。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as Date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant_core.bank_swing_pool import BANK_POOL
from quant_core.horizon import HorizonParams
from research.dual_strategy_backtest import (
    load_csv_directory,
    make_account1_strategy,
    make_account3_strategy,
)
from research.portfolio_backtest import BacktestConfig, run_portfolio_backtest
from research.position_backtest import run_horizon_backtest, with_params

MEAN_REVERT_GRID: tuple[dict, ...] = (
    {"name": "mr_base", "stop_loss_pct": 0.12, "take_profit_pct": 0.20, "min_hold_days": 15, "rsi_buy": 40.0, "near_low60_pct": 0.05, "ma120_floor": 0.90, "weekly_only": False},
    {"name": "mr_conservative", "stop_loss_pct": 0.15, "take_profit_pct": 0.25, "min_hold_days": 20, "rsi_buy": 35.0, "near_low60_pct": 0.05, "ma120_floor": 0.90, "weekly_only": False},
    {"name": "mr_loose", "stop_loss_pct": 0.12, "take_profit_pct": 0.20, "min_hold_days": 10, "rsi_buy": 45.0, "near_low60_pct": 0.08, "ma120_floor": None, "weekly_only": False},
    {"name": "mr_weekly", "stop_loss_pct": 0.12, "take_profit_pct": 0.20, "min_hold_days": 20, "rsi_buy": 40.0, "near_low60_pct": 0.05, "ma120_floor": 0.90, "weekly_only": True},
    {"name": "mr_wide_take", "stop_loss_pct": 0.15, "take_profit_pct": 0.30, "min_hold_days": 20, "rsi_buy": 40.0, "near_low60_pct": 0.05, "ma120_floor": 0.90, "weekly_only": False},
)

PULLBACK_GRID: tuple[dict, ...] = (
    {"name": "pb_base", "style": "trend_pullback", "stop_loss_pct": 0.12, "take_profit_pct": 0.20, "min_hold_days": 10, "rsi_buy": 50.0, "ma20_pullback_band": 0.02, "sell_on_ma60_recover": False, "weekly_only": False},
    {"name": "pb_tight", "style": "trend_pullback", "stop_loss_pct": 0.12, "take_profit_pct": 0.18, "min_hold_days": 10, "rsi_buy": 45.0, "ma20_pullback_band": 0.015, "sell_on_ma60_recover": False, "weekly_only": False},
    {"name": "pb_wide", "style": "trend_pullback", "stop_loss_pct": 0.15, "take_profit_pct": 0.25, "min_hold_days": 15, "rsi_buy": 50.0, "ma20_pullback_band": 0.03, "sell_on_ma60_recover": False, "weekly_only": False},
    {"name": "pb_weekly", "style": "trend_pullback", "stop_loss_pct": 0.12, "take_profit_pct": 0.20, "min_hold_days": 15, "rsi_buy": 50.0, "ma20_pullback_band": 0.02, "sell_on_ma60_recover": False, "weekly_only": True},
)


def _summarize_old(result) -> dict:
    trades = result.trades
    sells = trades[trades["side"] == "SELL"] if not trades.empty else trades
    n = int(len(sells))
    wins = int((sells["realized_pnl"] > 0).sum()) if n else 0
    return {
        "total_return": result.metrics.total_return,
        "max_drawdown": result.metrics.max_drawdown,
        "num_trades": n,
        "win_rate": (wins / n) if n else 0.0,
        "net_pnl": float(sells["realized_pnl"].sum()) if n else 0.0,
        "final_nav": float(result.nav["total_value"].iloc[-1]) if not result.nav.empty else None,
    }


def _pick(rows: list[dict]) -> dict | None:
    """优先 holdout 收益为正且回撤不太深；否则选 holdout 亏得最少的。"""

    if not rows:
        return None
    scored = []
    for row in rows:
        hold = row["holdout"]["metrics"]
        train = row["train"]["metrics"]
        if hold["num_trades"] < 3 and train["num_trades"] < 8:
            continue
            dd = abs(hold["max_drawdown"] or 0)
            if dd > 0.25:
                continue
        scored.append(row)
            dd = abs(hold["max_drawdown"] or 0)
            if dd > 0.25:
                continue

    return max(pool, key=key)


def _run_grid(bars, grid, *, style_default, cash, positions, budget, start, end, holdout) -> list[dict]:
    rows = []
    from datetime import timedelta

    train_last = holdout - timedelta(days=1)
    for spec in grid:
        name = spec["name"]
        changes = {k: v for k, v in spec.items() if k != "name"}
        params = with_params(
            HorizonParams(enabled=True, style=spec.get("style", style_default)),
            **{k: v for k, v in changes.items() if k != "style"},
        )
        print(f"  grid {name} ...", flush=True)
        train = run_horizon_backtest(
            bars, params, start=start, end=train_last,
            initial_cash=cash, max_positions=positions, buy_budget=budget,
        )
        hold = run_horizon_backtest(
            bars, params, start=holdout, end=end,
            initial_cash=cash, max_positions=positions, buy_budget=budget,
        )
        rows.append({"name": name, "train": train, "holdout": hold})
        tm, hm = train["metrics"], hold["metrics"]
        print(
            f"    train ret={tm['total_return']:+.2%} n={tm['num_trades']} hold={tm['median_hold_days']} | "
            f"holdout ret={hm['total_return']:+.2%} n={hm['num_trades']} dd={hm['max_drawdown']:.2%}",
            flush=True,
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=Path, default=ROOT / "data" / "backtest_bars")
    parser.add_argument("--start", type=Date.fromisoformat, default=Date(2024, 8, 1))
    parser.add_argument("--end", type=Date.fromisoformat, default=Date(2026, 9, 16))
    parser.add_argument("--holdout", type=Date.fromisoformat, default=Date(2026, 1, 5))
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "position_backtest")
    args = parser.parse_args()

    bars, audit = load_csv_directory(args.bars, allow_adjusted_research=True)
    # 丢掉 ETF（5 开头）以免和股票混池
    bars = {k: v for k, v in bars.items() if not str(k).zfill(6).startswith("5")}
    bank_codes = {p[0][-6:] for p in BANK_POOL}
    bank_bars = {k: v for k, v in bars.items() if str(k).zfill(6)[-6:] in bank_codes}
    stock_bars = {k: v for k, v in bars.items() if str(k).zfill(6)[-6:] not in bank_codes}
    if not stock_bars:
        stock_bars = bars

    print(f"标的 {len(bars)}（股票池 {len(stock_bars)} / 银行 {len(bank_bars)}），research_only={audit.research_only}")

    payload: dict = {
        "audit": {
            "research_only": audit.research_only,
            "n_symbols": len(bars),
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "holdout": args.holdout.isoformat(),
            "warning": audit.data_warning,
        },
        "accounts": {},
    }

    print("\n=== 旧策略基线（#1 MA10 / #3 5%-8%）===")
    old1 = run_portfolio_backtest(
        stock_bars,
        make_account1_strategy(trade_start=args.start, trade_end=args.end),
        BacktestConfig(initial_cash=100_000, max_positions=8, max_daily_new_positions=1, max_position_pct=0.15),
    )
    old3 = run_portfolio_backtest(
        stock_bars,
        make_account3_strategy(trade_start=args.start, trade_end=args.end),
        BacktestConfig(initial_cash=50_000, max_positions=5, max_daily_new_positions=2, max_position_pct=0.25),
    )
    payload["baseline"] = {"account1": _summarize_old(old1), "account3": _summarize_old(old3)}
    print("  #1", payload["baseline"]["account1"])
    print("  #3", payload["baseline"]["account3"])

    print("\n=== #1 学习仓 均值回归网格 本金10万 ===")
    a1 = _run_grid(
        stock_bars, MEAN_REVERT_GRID, style_default="mean_revert",
        cash=100_000, positions=5, budget=15_000,
        start=args.start, end=args.end, holdout=args.holdout,
    )
    pick1 = _pick(a1)
    payload["accounts"]["account1"] = {"grid": a1, "picked": pick1["name"] if pick1 else None}

    print("\n=== #3 波段仓 趋势回踩网格 本金5万 ===")
    a3 = _run_grid(
        stock_bars, PULLBACK_GRID, style_default="trend_pullback",
        cash=50_000, positions=3, budget=15_000,
        start=args.start, end=args.end, holdout=args.holdout,
    )
    pick3 = _pick(a3)
    payload["accounts"]["account3"] = {"grid": a3, "picked": pick3["name"] if pick3 else None}

    print("\n=== #4 银行仓 均值回归网格 本金3万 ===")
    a4_bars = bank_bars or stock_bars
    a4 = _run_grid(
        a4_bars, MEAN_REVERT_GRID, style_default="mean_revert",
        cash=30_000, positions=3, budget=8_000,
        start=args.start, end=args.end, holdout=args.holdout,
    )
    pick4 = _pick(a4)
    payload["accounts"]["account4"] = {"grid": a4, "picked": pick4["name"] if pick4 else None}

    args.output.mkdir(parents=True, exist_ok=True)
    compact = {
        "audit": payload["audit"],
        "baseline": payload["baseline"],
        "picked": {
            "account1": pick1,
            "account3": pick3,
            "account4": pick4,
        },
        "leaderboard": {
            "account1": [{"name": r["name"], "train": r["train"]["metrics"], "holdout": r["holdout"]["metrics"]} for r in a1],
            "account3": [{"name": r["name"], "train": r["train"]["metrics"], "holdout": r["holdout"]["metrics"]} for r in a3],
            "account4": [{"name": r["name"], "train": r["train"]["metrics"], "holdout": r["holdout"]["metrics"]} for r in a4],
        },
    }
    out = args.output / "leaderboard.json"
    out.write_text(json.dumps(compact, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    _write_md(args.output / "summary.md", compact)
    print(f"\n写到 {out}")
    print(f"入选 #1={compact['picked']['account1'] and compact['picked']['account1']['name']} "
          f"#3={compact['picked']['account3'] and compact['picked']['account3']['name']} "
          f"#4={compact['picked']['account4'] and compact['picked']['account4']['name']}")
    return 0


def _write_md(path: Path, compact: dict) -> None:
    lines = [
        "# 中长线回测摘要",
        "",
        f"- 区间 `{compact['audit']['start']}` → `{compact['audit']['end']}`，holdout 自 `{compact['audit']['holdout']}`",
        f"- 标的数 {compact['audit']['n_symbols']}；前复权研究数据，不得当实盘证据",
        "",
        "## 旧策略基线",
        "",
        "| 账户 | 收益 | 回撤 | 已平仓 | 胜率 | 净盈亏 |",
        "|------|-----:|-----:|-------:|-----:|-------:|",
    ]
    for key, label in (("account1", "#1 旧MA10"), ("account3", "#3 旧5%/8%")):
        m = compact["baseline"][key]
        lines.append(
            f"| {label} | {m['total_return']:+.2%} | {m['max_drawdown']:.2%} | {m['num_trades']} | "
            f"{m['win_rate']:.0%} | {m['net_pnl']:.0f} |"
        )
    lines += ["", "## 入选参数", ""]
    for key, label in (("account1", "#1"), ("account3", "#3"), ("account4", "#4")):
        picked = compact["picked"].get(key)
        if not picked:
            lines.append(f"- {label}：无入选")
            continue
        h = picked["holdout"]["metrics"]
        lines.append(
            f"- **{label} `{picked['name']}`** holdout 收益 {h['total_return']:+.2%} / "
            f"回撤 {h['max_drawdown']:.2%} / {h['num_trades']} 笔 / 中位持有 {h['median_hold_days']} 日"
        )
    lines += ["", "## 网格", ""]
    for key, label in (("account1", "#1"), ("account3", "#3"), ("account4", "#4")):
        lines += [f"### {label}", "", "| 名称 | 训练收益 | 训练笔数 | holdout收益 | holdout笔数 | holdout回撤 | 中位持有 |",
                  "|------|--------:|--------:|------------:|-----------:|-----------:|--------:|"]
        for row in compact["leaderboard"][key]:
            t, h = row["train"], row["holdout"]
            lines.append(
                f"| {row['name']} | {t['total_return']:+.2%} | {t['num_trades']} | "
                f"{h['total_return']:+.2%} | {h['num_trades']} | {h['max_drawdown']:.2%} | {h['median_hold_days']} |"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
