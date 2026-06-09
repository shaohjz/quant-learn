"""scripts/backfill_sell_signal_reason.py — REQ-058: 回填历史 SELL 成交的 NULL signal_reason

扫描 sim_trades 中 direction='SELL' 且 signal_reason IS NULL 的记录，
用 build_sell_signal_reason 生成标准化占位值并回填。

用法：
    cd quant-learn
    python scripts/backfill_sell_signal_reason.py [--db data/sim_live_mirror.db] [--dry-run]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sim.sell_signal_audit import build_sell_signal_reason


def backfill(db_path: str = "data/sim_live_mirror.db", dry_run: bool = False) -> int:
    db = Path(ROOT) / db_path
    if not db.exists():
        print(f"❌ 数据库不存在: {db}")
        return 0

    conn = sqlite3.connect(str(db), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        # 查找所有 signal_reason 为 NULL 的 SELL 成交
        rows = cur.execute(
            "SELECT id, stock_code, stock_name, price, quantity, trade_date, account_id "
            "FROM sim_trades WHERE direction='SELL' AND signal_reason IS NULL"
        ).fetchall()

        if not rows:
            print("✅ 无需回填：所有 SELL 成交的 signal_reason 均非空")
            return 0

        print(f"📋 发现 {len(rows)} 笔 SELL 成交的 signal_reason 为 NULL：")
        updated = 0
        for r in rows:
            sr = build_sell_signal_reason("unknown_sell", trigger_price=r["price"], volume=r["quantity"])
            print(f"  id={r['id']} {r['stock_name'] or r['stock_code']} "
                  f"@{r['price']}x{r['quantity']} → {sr}")
            if not dry_run:
                cur.execute(
                    "UPDATE sim_trades SET signal_reason = ? WHERE id = ?",
                    (sr, r["id"]),
                )
                updated += 1

        if not dry_run:
            conn.commit()
            print(f"✅ 回填完成：更新 {updated} 笔记录")
        else:
            print(f"🔍 dry-run 模式：未实际更新（共 {len(rows)} 笔待回填）")

        return updated
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回填 SELL 成交的 NULL signal_reason")
    parser.add_argument("--db", default="data/sim_live_mirror.db", help="数据库路径")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际更新")
    args = parser.parse_args()
    backfill(args.db, args.dry_run)
