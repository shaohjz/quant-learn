"""
REQ-058 巡检：清理清仓后仍悬挂的 threshold_state。

覆盖场景：
1) sim_positions 行已 DELETE（LEFT JOIN 无仓）
2) quantity<=0 幽灵行（历史 UPDATE 路径残留）
3) 全账户（不再写死 account_id=1）
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.config_resolver import resolve_db_path
from sim.sell_signal_audit import (
    ACTIVE_ORPHAN_STATUSES,
    SELL_RULES,
    expire_thresholds_on_flat,
)


def patrol(db_path: Path | None = None) -> int:
    db = Path(db_path) if db_path else resolve_db_path()
    if not db.exists():
        print(f"[{date.today()}] DB missing: {db}")
        return 0

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        tables = {
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "threshold_state" not in tables:
            print(f"[{date.today()}] No threshold_state table")
            return 0

        rule_ph = ",".join("?" for _ in SELL_RULES)
        status_ph = ",".join("?" for _ in ACTIVE_ORPHAN_STATUSES)

        # 有活跃卖出规则、但任意账户均无 quantity>0 持仓
        rows = cur.execute(
            f"""
            SELECT ts.id, ts.stock_code, ts.status, ts.rule_name
              FROM threshold_state ts
             WHERE ts.status IN ({status_ph})
               AND ts.rule_name IN ({rule_ph})
               AND NOT EXISTS (
                   SELECT 1 FROM sim_positions sp
                    WHERE sp.quantity > 0
                      AND (
                           sp.stock_code = ts.stock_code
                           OR REPLACE(UPPER(sp.stock_code), 'SH', '') =
                              REPLACE(UPPER(ts.stock_code), 'SH', '')
                           OR REPLACE(UPPER(sp.stock_code), 'SZ', '') =
                              REPLACE(UPPER(ts.stock_code), 'SZ', '')
                      )
               )
            """,
            (*ACTIVE_ORPHAN_STATUSES, *SELL_RULES),
        ).fetchall()

        if not rows:
            print(f"[{date.today()}] No orphan records found")
            return 0

        cleaned = 0
        for row in rows:
            n = expire_thresholds_on_flat(
                cur,
                row["stock_code"],
                note="patrol: 无持仓悬挂清理",
            )
            cleaned += n
        conn.commit()
        print(
            f"[{date.today()}] Cleaned {cleaned} orphan threshold_state "
            f"record(s) across {len(rows)} candidate row(s)"
        )
        return cleaned
    finally:
        conn.close()


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    raise SystemExit(0 if patrol(path) >= 0 else 1)
