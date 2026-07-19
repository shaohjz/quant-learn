#!/usr/bin/env python
"""
scripts/capital_status.py — 资金一致性自查（只读）

一处看清所有账户：config 声明 vs DB 实际。用于排查「资金有点乱 / 不一致」。

真源约定：
  - config.yaml accounts.* = 资金声明的唯一入口
  - DB.initial_cash = NAV/收益率基准的权威（REQ-094，反映历史资金事件）
  - 二者不一致时本脚本只告警，不自动改 DB。要重置用 scripts/reset_account.py

用法：
  python scripts/capital_status.py
  python scripts/capital_status.py --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.config import get_account_config, load_config  # noqa: E402

DB_PATH = ROOT / "data" / "sim_live_mirror.db"


def collect() -> list[dict]:
    cfg = load_config()
    accounts = cfg.get("accounts") or {}
    ids = sorted({int(v.get("account_id")) for v in accounts.values()
                  if isinstance(v, dict) and v.get("account_id") is not None})
    if not ids:
        ids = [1, 3]

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows: list[dict] = []
    try:
        for aid in ids:
            acct = get_account_config(aid)
            key = acct.get("key")
            # real（account_id=2）是实际持仓镜像，由 sync_real_position 维护，不在模拟 DB
            is_mirror = key == "real"
            cfg_cash = float(acct.get("initial_cash") or 0)
            db_row = conn.execute(
                "SELECT account_name, cash, total_value, initial_cash "
                "FROM sim_account WHERE id=?",
                (aid,),
            ).fetchone()
            db = dict(db_row) if db_row else {}
            db_initial = float(db.get("initial_cash") or 0) if db else None
            if is_mirror:
                consistent = True  # 镜像账户不参与模拟资金一致性判定
            else:
                consistent = db_initial is not None and abs(db_initial - cfg_cash) < 0.01
            rows.append({
                "account_id": aid,
                "key": key,
                "name": acct.get("account_name"),
                "is_mirror": is_mirror,
                "config_initial_cash": cfg_cash,
                "db_initial_cash": db_initial,
                "db_cash": float(db.get("cash") or 0) if db else None,
                "db_total_value": float(db.get("total_value") or 0) if db else None,
                "in_db": bool(db),
                "consistent": consistent,
            })
    finally:
        conn.close()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="资金一致性自查（只读）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    rows = collect()
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    print("=== 资金一致性自查（config vs DB）===")
    print(f"DB: {DB_PATH}")
    print(f"{'ID':>3} {'key':<8} {'名称':<14} {'config':>10} {'DB初始':>10} {'DB现金':>10} {'DB总值':>10}  一致?")
    all_ok = True
    for r in rows:
        db_i = "—" if r["db_initial_cash"] is None else f"{r['db_initial_cash']:,.0f}"
        db_c = "—" if r["db_cash"] is None else f"{r['db_cash']:,.0f}"
        db_t = "—" if r["db_total_value"] is None else f"{r['db_total_value']:,.0f}"
        if r.get("is_mirror"):
            flag = "镜像"
        elif not r["in_db"]:
            flag = "⚠️ 缺"
        elif r["consistent"]:
            flag = "✅"
        else:
            flag = "⚠️ 不一致"
        if not r["consistent"]:
            all_ok = False
        print(f"{r['account_id']:>3} {str(r['key']):<8} {str(r['name']):<14} "
              f"{r['config_initial_cash']:>10,.0f} {db_i:>10} {db_c:>10} {db_t:>10}  {flag}")

    print()
    if all_ok:
        print("✅ 全部一致")
    else:
        print("⚠️ 存在不一致。NAV 基准以 DB 为准（REQ-094）；如需按 config 重置：")
        print("   python scripts/reset_account.py            # 重置全部")
        print("   python scripts/reset_account.py --only swing")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
