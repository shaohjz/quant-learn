"""
cleanup_zero_quantity_positions.py — 清理 sim_positions 中 quantity=0 的残留记录
================================================================================
TASK-20260718-2003-001: 清仓后 sim_positions 残留记录未清理

背景:
  sim/engine.py sell() 在 remain<=0 时做了 UPDATE SET quantity=0 而非 DELETE，
  导致已清仓股票仍在 sim_positions 表中留下空记录。虽然 get_positions() 已过滤
  quantity>0，但这些残留仍可能被未使用?WHERE quantity>0 的查询误算入统计。

修复内容:
  1. 备份：将 quantity=0 的记录写入 sim_positions_archive 表（快照版）
  2. 清理：DELETE FROM sim_positions WHERE quantity=0
  3. 事务保护：备份和清理在同一事务中执行，任何步骤失败即回滚

用法:
  python scripts/cleanup_zero_quantity_positions.py [--db DATA/sim_live_mirror.db] [--dry-run]
"""

import os
import sys
import sqlite3
import json
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _get_db_path(db_arg: Optional[str] = None) -> str:
    if db_arg:
        return db_arg
    return os.environ.get('QUANT_DB_PATH', str(ROOT / 'data' / 'sim_live_mirror.db'))


def _ensure_archive_table(conn: sqlite3.Connection) -> None:
    """确保归档表存在，结构与 sim_positions 一致 + 归档时间戳列。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sim_positions_archive (
            id INTEGER,
            account_id INTEGER,
            stock_code TEXT,
            stock_name TEXT,
            quantity INTEGER,
            avg_cost REAL,
            current_price REAL,
            market_value REAL,
            pnl REAL,
            pnl_pct REAL,
            trailing_stop_price REAL,
            highest_price REAL,
            updated_at TIMESTAMP,
            archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            archive_reason TEXT DEFAULT 'zero_quantity_cleanup'
        )
    """)


def backup_zero_positions(conn: sqlite3.Connection) -> int:
    """将 quantity=0 的记录备份到 sim_positions_archive 表。返回备份条数。"""
    _ensure_archive_table(conn)
    
    rows = conn.execute("""
        SELECT id, account_id, stock_code, stock_name, quantity, avg_cost,
               current_price, market_value, pnl, pnl_pct,
               trailing_stop_price, highest_price, updated_at
        FROM sim_positions WHERE quantity = 0
    """).fetchall()
    
    if not rows:
        return 0
    
    for row in rows:
        conn.execute("""
            INSERT INTO sim_positions_archive
                (id, account_id, stock_code, stock_name, quantity, avg_cost,
                 current_price, market_value, pnl, pnl_pct,
                 trailing_stop_price, highest_price, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, row)
    
    return len(rows)


def delete_zero_positions(conn: sqlite3.Connection) -> int:
    """删除 quantity=0 的残留记录。返回删除条数。"""
    cursor = conn.execute("DELETE FROM sim_positions WHERE quantity = 0")
    return cursor.rowcount


def run_cleanup(db_path: str, dry_run: bool = False) -> dict:
    """执行清理流程，返回结果字典。"""
    result = {
        "db_path": db_path,
        "dry_run": dry_run,
        "timestamp": datetime.now().isoformat(),
        "backup_count": 0,
        "delete_count": 0,
        "zero_count_before": 0,
        "total_count_before": 0,
        "total_count_after": 0,
        "zero_count_after": 0,
        "errors": [],
    }

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    try:
        # ── 清点 ──
        result["zero_count_before"] = conn.execute(
            "SELECT COUNT(*) FROM sim_positions WHERE quantity = 0"
        ).fetchone()[0]
        result["total_count_before"] = conn.execute(
            "SELECT COUNT(*) FROM sim_positions"
        ).fetchone()[0]

        if result["zero_count_before"] == 0:
            result["message"] = "没有 quantity=0 的残留记录，无需清理"
            print(f"✅ {result['message']}")
            return result

        # ── 打印将要清理的记录 ──
        rows = conn.execute("""
            SELECT id, account_id, stock_code, stock_name, quantity, avg_cost,
                   current_price, market_value, pnl, pnl_pct, updated_at
            FROM sim_positions WHERE quantity = 0
        """).fetchall()
        
        print(f"🔍 发现 {len(rows)} 条 quantity=0 的残留记录：")
        for r in rows:
            print(f"  id={r['id']} {r['stock_code']} {r['stock_name']} "
                  f"qty={r['quantity']} avg_cost={r['avg_cost']} "
                  f"pnl={r['pnl']} pnl_pct={r['pnl_pct']}%"
                  f" updated={r['updated_at']}")

        if dry_run:
            result["message"] = f"DRY RUN: 发现 {len(rows)} 条残留记录，未执行实际清理"
            print(f"\n⚠️ DRY RUN 模式：未执行实际清理。去掉 --dry-run 参数后重新运行以执行清理。")
            return result

        # ── 事务：备份 + 清理 ──
        try:
            conn.execute("BEGIN")
            
            # Step 1: 备份
            result["backup_count"] = backup_zero_positions(conn)
            print(f"📋 已备份 {result['backup_count']} 条记录到 sim_positions_archive")

            # Step 2: 删除
            result["delete_count"] = delete_zero_positions(conn)
            print(f"🗑️ 已删除 {result['delete_count']} 条残留记录")

            conn.execute("COMMIT")
            
            # ── 验证 ──
            result["zero_count_after"] = conn.execute(
                "SELECT COUNT(*) FROM sim_positions WHERE quantity = 0"
            ).fetchone()[0]
            result["total_count_after"] = conn.execute(
                "SELECT COUNT(*) FROM sim_positions"
            ).fetchone()[0]
            
            archive_count = conn.execute(
                "SELECT COUNT(*) FROM sim_positions_archive"
            ).fetchone()[0]

            if result["zero_count_after"] == 0:
                result["message"] = (
                    f"清理成功: 备份 {result['backup_count']} 条, "
                    f"删除 {result['delete_count']} 条, "
                    f"归档表共 {archive_count} 条, "
                    f"持仓从 {result['total_count_before']} 条减少到 {result['total_count_after']} 条"
                )
                print(f"\n✅ {result['message']}")
            else:
                result["errors"].append(
                    f"清理后仍有 {result['zero_count_after']} 条 quantity=0 记录"
                )
                print(f"\n❌ 异常: 清理后仍有 {result['zero_count_after']} 条 quantity=0 记录")

        except Exception as e:
            conn.execute("ROLLBACK")
            result["errors"].append(f"事务执行失败: {e}")
            print(f"\n❌ 事务回滚: {e}")
    
    finally:
        conn.close()
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description="清理 sim_positions 中 quantity=0 的残留记录"
    )
    parser.add_argument(
        "--db", default=None,
        help="数据库路径（默认: data/sim_live_mirror.db）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅检查不执行清理"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式输出结果"
    )
    
    args = parser.parse_args()
    db_path = _get_db_path(args.db)
    
    if not os.path.exists(db_path):
        print(f"❌ 数据库不存在: {db_path}", file=sys.stderr)
        sys.exit(1)

    result = run_cleanup(db_path, dry_run=args.dry_run)
    
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    # 退出码: 有错误则返回 1
    if result["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
