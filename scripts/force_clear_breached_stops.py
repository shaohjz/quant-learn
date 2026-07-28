#!/usr/bin/env python3
"""强制清仓：跌破止损仍有持仓的残留股（REQ-101/104/106 产机止血）。

用法（产机）：
  .venv\\Scripts\\python.exe -u scripts\\force_clear_breached_stops.py --dry-run
  .venv\\Scripts\\python.exe -u scripts\\force_clear_breached_stops.py --account 1
  .venv\\Scripts\\python.exe -u scripts\\force_clear_breached_stops.py --codes 000725,300017,300146

默认 account=1（learn）。用 trailing_stop_price / 默认成本×0.95 判破止损。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DB_PATH = ROOT / "data" / "sim_live_mirror.db"


def _effective_stop(row: sqlite3.Row) -> float:
    trail = float(row["trailing_stop_price"] or 0)
    cost = float(row["avg_cost"] or 0)
    default_stop = round(cost * 0.95, 2) if cost > 0 else 0.0
    return max(trail, default_stop)


def main() -> int:
    ap = argparse.ArgumentParser(description="强制清仓破止损残留")
    ap.add_argument("--account", type=int, default=1)
    ap.add_argument("--codes", default="", help="逗号分隔 6 位码；空=扫描全部破止损")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args()

    if not args.db.exists():
        print(f"DB 不存在: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT stock_code, stock_name, quantity, avg_cost, current_price, trailing_stop_price "
        "FROM sim_positions WHERE account_id=? AND quantity>0",
        (args.account,),
    ).fetchall()
    conn.close()

    want = {c.strip().zfill(6)[-6:] for c in args.codes.split(",") if c.strip()}
    targets = []
    for r in rows:
        code = str(r["stock_code"]).zfill(6)[-6:]
        if want and code not in want:
            continue
        price = float(r["current_price"] or 0) or float(r["avg_cost"] or 0)
        stop = _effective_stop(r)
        if stop <= 0:
            continue
        if price <= stop or (want and code in want):
            targets.append((code, r["stock_name"], int(r["quantity"]), price, stop))

    if not targets:
        print("无破止损残留，无需清仓")
        return 0

    print(f"将清仓 {len(targets)} 只（account={args.account}）:")
    for code, name, qty, price, stop in targets:
        print(f"  {code} {name} qty={qty} price={price:.2f} stop={stop:.2f}")

    if args.dry_run:
        print("DRY RUN，未下单")
        return 0

    from sim_executor import execute_trade, set_account_id

    set_account_id(args.account)
    ok_n = 0
    for code, name, qty, price, stop in targets:
        rule = {
            "code": code,
            "name": name or code,
            "level": "hard_stop",
            "trigger": stop,
            "dir": "below",
            "message": f"force_clear_breached_stops 清仓（止损¥{stop:.2f}）",
            "source": "force_clear",
        }
        result = execute_trade(rule, price)
        trade = result.get("trade")
        if trade is not None:
            ok_n += 1
            print(f"✅ {code} {result.get('message')}")
        else:
            print(f"❌ {code} 失败: {result.get('message')} action={result.get('action')}")
    print(f"完成 {ok_n}/{len(targets)}")
    return 0 if ok_n == len(targets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
