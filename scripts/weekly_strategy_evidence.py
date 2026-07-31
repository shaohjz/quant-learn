"""生成每周策略证据快照；只读交易库，不改配置、不触发交易。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.strategy_evidence import (
    build_strategy_evidence,
    load_optimization_report,
    read_trade_records,
)

DEFAULT_DB = ROOT / "data" / "sim_live_mirror.db"
DEFAULT_OUTPUT = ROOT / "output" / "promotion"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读生成 account 1/3 策略晋级证据")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 交易库路径")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="输出目录（文件名固定为日期.json），也可传入明确的 .json 文件路径",
    )
    parser.add_argument(
        "--optimization-report",
        type=Path,
        help="可选的 dual optimize JSON；缺省时晋级证据明确标记回测报告缺失",
    )
    return parser


def output_path(value: Path, as_of: date) -> Path:
    return value if value.suffix.lower() == ".json" else value / f"{as_of.isoformat()}.json"


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    today = datetime.now().astimezone().date()
    try:
        trades = read_trade_records(args.db, as_of=today)
        optimization_report = (
            load_optimization_report(args.optimization_report) if args.optimization_report is not None else None
        )
        report = build_strategy_evidence(
            trades,
            as_of=today,
            optimization_report=optimization_report,
        )
        destination = output_path(args.output, today)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (FileNotFoundError, RuntimeError, OSError, TypeError, ValueError) as exc:
        print(f"生成策略证据失败: {exc}", file=sys.stderr)
        return 2

    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
