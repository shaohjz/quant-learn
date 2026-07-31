"""只读比较双账户 baseline 与候选策略参数。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as Date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.dual_strategy_backtest import load_csv_directory
from research.strategy_shadow import compare_strategy_shadow, load_candidate_params


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_directory", type=Path, help="每个标的一份 CSV 的目录")
    parser.add_argument("--start", type=Date.fromisoformat, required=True, help="对照开始日 YYYY-MM-DD")
    parser.add_argument("--end", type=Date.fromisoformat, required=True, help="对照结束日 YYYY-MM-DD")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--optimize-json",
        type=Path,
        help="optimize 输出 JSON，从 accounts.*.final_best_params 读取参数",
    )
    source.add_argument(
        "--params-json",
        type=Path,
        help='显式参数 JSON，格式为 {"account1": {...}, "account3": {...}}',
    )
    parser.add_argument("--output", type=Path, help="JSON 输出文件；不传则写 stdout")
    parser.add_argument(
        "--allow-adjusted-research",
        action="store_true",
        help="显式允许缺少 raw 标记或复权 CSV；仅作研究并保留风险警告",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.end < args.start:
        raise SystemExit("--end 不能早于 --start")

    params_path = args.optimize_json or args.params_json
    source_type = "optimize_final_best_params" if args.optimize_json else "explicit_params"
    try:
        candidate_params = load_candidate_params(
            params_path,
            optimize_report=args.optimize_json is not None,
        )
        bars, data_audit = load_csv_directory(
            args.csv_directory,
            allow_adjusted_research=args.allow_adjusted_research,
        )
        payload = compare_strategy_shadow(
            bars,
            start=args.start,
            end=args.end,
            candidate_params=candidate_params,
            data_audit=data_audit,
            candidate_source={"type": source_type, "path": str(params_path)},
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    else:
        print(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
