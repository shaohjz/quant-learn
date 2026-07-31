#!/usr/bin/env python
"""
scripts/reset_account.py — 彻底重置模拟盘账户（force 模式，无交互）

默认重置：
  #1 learn        — config accounts.learn.initial_cash（默认 10万）
  #3 swing_trade  — config accounts.swing.initial_cash（默认 5万）

用法：
  python scripts/reset_account.py
  python scripts/reset_account.py --only learn
  python scripts/reset_account.py --only swing
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.config_resolver import resolve_db_path

SIM_DB = str(resolve_db_path())
TODAY = date.today().strftime("%Y-%m-%d")
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
ACCOUNTS = cfg.get("accounts") or {}

TARGETS = {
    "learn": {
        "id": int(ACCOUNTS.get("learn", {}).get("account_id", 1)),
        "name": ACCOUNTS.get("learn", {}).get("account_name", "learn"),
        "cash": float(ACCOUNTS.get("learn", {}).get("initial_cash", 100000.0)),
    },
    "swing": {
        "id": int(ACCOUNTS.get("swing", {}).get("account_id", 3)),
        "name": ACCOUNTS.get("swing", {}).get("account_name", "swing_trade"),
        "cash": float(ACCOUNTS.get("swing", {}).get("initial_cash", 50000.0)),
    },
}

# 与账户绑定的表（存在才清）
ACCOUNT_TABLES = (
    "sim_positions",
    "sim_trades",
    "sim_orders",
    "sim_fills",
    "sim_daily_nav",
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _ensure_account(conn: sqlite3.Connection, acct_id: int, name: str, cash: float) -> None:
    row = conn.execute("SELECT id FROM sim_account WHERE id=?", (acct_id,)).fetchone()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sim_account)").fetchall()}
    if row:
        sets = ["cash=?", "total_value=?", "updated_at=?"]
        vals: list = [cash, cash, NOW]
        if "initial_cash" in cols:
            sets.append("initial_cash=?")
            vals.append(cash)
        if "account_name" in cols:
            sets.append("account_name=?")
            vals.append(name)
        vals.append(acct_id)
        conn.execute(f"UPDATE sim_account SET {', '.join(sets)} WHERE id=?", vals)
    else:
        if "account_name" in cols and "initial_cash" in cols:
            conn.execute(
                "INSERT INTO sim_account (id, account_name, initial_cash, cash, total_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (acct_id, name, cash, cash, cash, NOW),
            )
        else:
            conn.execute(
                "INSERT INTO sim_account (id, cash, total_value) VALUES (?, ?, ?)",
                (acct_id, cash, cash),
            )


def reset_one(conn: sqlite3.Connection, key: str) -> None:
    t = TARGETS[key]
    acct_id, name, cash = t["id"], t["name"], t["cash"]
    print(f"\n--- 重置 {key} (#{acct_id} {name}) -> ¥{cash:,.0f} ---")

    for table in ACCOUNT_TABLES:
        if not _table_exists(conn, table):
            print(f"  skip {table} (无表)")
            continue
        cur = conn.execute(f"DELETE FROM {table} WHERE account_id=?", (acct_id,))
        print(f"  ✅ 清空 {table}: {cur.rowcount} 条")

    _ensure_account(conn, acct_id, name, cash)
    print(f"  ✅ 账户: cash=total=initial={cash}")

    if _table_exists(conn, "sim_daily_nav"):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sim_daily_nav)").fetchall()}
        if {"account_id", "trade_date", "total_value", "cash"} <= cols:
            extra = ""
            vals: list = [acct_id, TODAY, cash, cash]
            if "market_value" in cols:
                extra += ", market_value"
                vals.append(0)
            if "daily_return" in cols:
                extra += ", daily_return"
                vals.append(0)
            if "cumulative_return" in cols:
                extra += ", cumulative_return"
                vals.append(0)
            if "max_drawdown" in cols:
                extra += ", max_drawdown"
                vals.append(0)
            if "created_at" in cols:
                extra += ", created_at"
                vals.append(NOW)
            placeholders = ",".join("?" * len(vals))
            conn.execute(
                f"INSERT INTO sim_daily_nav "
                f"(account_id, trade_date, total_value, cash{extra}) VALUES ({placeholders})",
                vals,
            )
            print(f"  ✅ 新 NAV: {TODAY} total={cash}")


def main() -> int:
    parser = argparse.ArgumentParser(description="重置模拟盘账户资金")
    parser.add_argument(
        "--only",
        choices=("learn", "swing", "all"),
        default="all",
        help="只重置指定账户（默认 all）",
    )
    args = parser.parse_args()
    keys = list(TARGETS) if args.only == "all" else [args.only]

    print("=== 重置模拟盘账户 ===")
    print(f"  DB: {SIM_DB}")
    print(f"  日期: {TODAY}")
    for k in keys:
        print(f"  目标 {k}: ¥{TARGETS[k]['cash']:,.0f}")

    conn = sqlite3.connect(SIM_DB)
    try:
        for k in keys:
            reset_one(conn, k)
        conn.commit()
    finally:
        conn.close()

    print("\n✅ 重置完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
