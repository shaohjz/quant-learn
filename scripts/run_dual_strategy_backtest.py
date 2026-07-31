#!/usr/bin/env python3
"""从 CSV 目录运行账户 #1/#3 基线或嵌套 walk-forward 回测。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as Date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.dual_strategy_backtest import (
    load_csv_directory,
    optimize_dual_strategies,
    run_dual_strategy_backtest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_directory", type=Path, help="每个标的一份 CSV 的目录")
    parser.add_argument("--mode", choices=("baseline", "optimize"), default="baseline")
    parser.add_argument("--start", type=Date.fromisoformat, required=True, help="交易窗口开始日 YYYY-MM-DD")
    parser.add_argument("--end", type=Date.fromisoformat, required=True, help="交易窗口结束日 YYYY-MM-DD")
    parser.add_argument(
        "--holdout",
        type=Date.fromisoformat,
        help="最终 holdout 开始日；optimize 模式下 holdout 截止到 --end",
    )
    parser.add_argument("--output", type=Path, help="JSON 输出文件；不传则写 stdout")
    parser.add_argument(
        "--allow-adjusted-research",
        action="store_true",
        help="允许缺少 raw 标记或复权 CSV，仅作研究并写入风险审计",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.end < args.start:
        raise SystemExit("--end 不能早于 --start")
    if args.mode == "baseline" and args.holdout is not None:
        raise SystemExit("--holdout 仅用于 optimize 模式")

    bars, audit = load_csv_directory(
        args.csv_directory,
        allow_adjusted_research=args.allow_adjusted_research,
    )
    if args.mode == "baseline":
        payload = run_dual_strategy_backtest(
            bars,
            start=args.start,
            end=args.end,
            data_audit=audit,
        )
    else:
        payload = optimize_dual_strategies(
            bars,
            start=args.start,
            end=args.end,
            holdout_start=args.holdout,
            data_audit=audit,
        )

    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
