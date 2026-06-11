"""REQ-027: 盘前交易纪律打卡 / 盘后知行合一评分 CLI.

Examples:
  python scripts/discipline_checkin.py checkin --day 2026-06-01 --max-daily-trades 3 --min-cash-pct 20 --notes "只做计划内交易"
  python scripts/discipline_checkin.py score --day 2026-06-01
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QUANT_DB_PATH", str(ROOT / "data" / "sim_live_mirror.db"))

from sim.discipline import (
    ensure_trade_discipline_tables,
    get_discipline_plan,
    render_discipline_score,
    score_trade_discipline,
    upsert_discipline_plan,
)

DB = Path(os.environ["QUANT_DB_PATH"])


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    return conn


def main() -> int:
    parser = argparse.ArgumentParser(description="交易纪律打卡与执行评分")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("checkin", help="写入/更新盘前纪律配置")
    p.add_argument("--account-id", type=int, default=1)
    p.add_argument("--day", default=date.today().isoformat())
    p.add_argument("--max-daily-trades", type=int)
    p.add_argument("--max-buy-trades", type=int)
    p.add_argument("--max-sell-trades", type=int)
    p.add_argument("--max-turnover-pct", type=float)
    p.add_argument("--max-single-position-pct", type=float)
    p.add_argument("--min-cash-pct", type=float)
    p.add_argument("--allow-chase", action="store_true", help="允许追高；默认不允许")
    p.add_argument("--notes", default="")
    p.add_argument("--json", action="store_true")

    s = sub.add_parser("score", help="按当日成交记录生成执行度评分")
    s.add_argument("--account-id", type=int, default=1)
    s.add_argument("--day", default=date.today().isoformat())
    s.add_argument("--json", action="store_true")

    g = sub.add_parser("show", help="查看某日纪律配置")
    g.add_argument("--account-id", type=int, default=1)
    g.add_argument("--day", default=date.today().isoformat())
    g.add_argument("--json", action="store_true")

    args = parser.parse_args()
    conn = get_conn()
    try:
        ensure_trade_discipline_tables(conn)
        if args.cmd == "checkin":
            plan = upsert_discipline_plan(
                conn,
                args.account_id,
                args.day,
                max_daily_trades=args.max_daily_trades,
                max_buy_trades=args.max_buy_trades,
                max_sell_trades=args.max_sell_trades,
                max_turnover_pct=args.max_turnover_pct,
                max_single_position_pct=args.max_single_position_pct,
                min_cash_pct=args.min_cash_pct,
                no_chase=not args.allow_chase,
                notes=args.notes,
            )
            data = plan.__dict__
            conn.commit()
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print(f"✅ 已打卡 {args.day} 交易纪律：日交易≤{plan.max_daily_trades}笔，现金≥{plan.min_cash_pct*100:.0f}%")
        elif args.cmd == "score":
            result = score_trade_discipline(conn, args.account_id, args.day, persist=True)
            conn.commit()
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(render_discipline_score(result, compact=False))
        elif args.cmd == "show":
            plan = get_discipline_plan(conn, args.account_id, args.day)
            data = plan.__dict__
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print(f"{args.day} account={args.account_id} source={plan.source}: {data}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
