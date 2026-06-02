"""REQ-058: SELL 成交-信号对账复盘脚本（命令行）。

用法：
  python scripts/sell_signal_reconcile.py [--day YYYY-MM-DD] [--db <path>]
       [--accounts 1,2] [--push]

行为：
  - 默认对 account_id=1(sim) 与 2(real) 当日 SELL 成交与 threshold_state 卖出信号对账。
  - 发现缺口（orphan_sells / unmatched_signals）时退出码=1，便于上游告警；
    若指定 --push，则把缺口简报推送到企微（channel=wecom, to=T60540021A）。
  - 无缺口时退出码=0。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.sell_signal_audit import audit_all_accounts, format_recon_report  # noqa: E402

DEFAULT_DB = ROOT / "data" / "sim_live_mirror.db"
WECOM_TO = "T60540021A"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="REQ-058 SELL 成交-信号对账")
    p.add_argument("--day", default=date.today().isoformat(), help="对账日期 YYYY-MM-DD")
    p.add_argument("--db", default=str(DEFAULT_DB), help="sim*.db 路径")
    p.add_argument("--accounts", default="1,2", help="账户ID列表，逗号分隔")
    p.add_argument("--push", action="store_true", help="发现缺口时推送企微告警")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    accounts = tuple(int(x) for x in args.accounts.split(",") if x.strip())
    db_path = Path(args.db)
    results = audit_all_accounts(args.day, db_path, account_ids=accounts)
    report = format_recon_report(results)
    print(f"=== SELL 成交-信号对账 {args.day} ({db_path.name}) ===")
    print(report)

    has_gap = any(r.has_gap for r in results.values())
    if has_gap and args.push:
        try:
            from scripts.notify import send_text  # type: ignore
            send_text(f"⚠️ SELL成交-信号对账缺口 {args.day}\n{report}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 推送失败（不影响对账结果）: {e}")
    return 1 if has_gap else 0


if __name__ == "__main__":
    raise SystemExit(main())
