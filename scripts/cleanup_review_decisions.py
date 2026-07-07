"""
cleanup_review_decisions.py — TASK-20260702-2004-005
======================================================================
清理 review_decisions 表中的历史冗余日志。

问题：_write_review_decision() 在 30 分钟冷静期内每次买入信号检查都无去重写入，
导致 daily_buy_budget_guard 同一 (stock_code, trade_date, decision_type) 重复 3-4 条。

策略：
1. 对于 daily_buy_budget_guard / daily_new_position_limit 等风控拒绝类型：
   同一 (account_id, stock_code, trade_date, decision_type) 保留最早一条（MIN(id)）
2. 对于 buy / trend_break_buy 等允许类型：
   保留最早一条，删除其他

用法：
  python scripts/cleanup_review_decisions.py          # dry-run 模式（只分析不删除）
  python scripts/cleanup_review_decisions.py --commit # 真正执行删除
  python scripts/cleanup_review_decisions.py --show   # 显示将被删除的记录详情
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB_PATH = ROOT / "data" / "sim_live_mirror.db"


def analyze_duplicates(conn: sqlite3.Connection) -> list[dict]:
    """查找需要清理的重复记录，返回 [(stock_code, trade_date, decision_type, keep_id, to_delete_ids), ..]"""
    groups = conn.execute("""
        SELECT stock_code, trade_date, decision_type, account_id,
               COUNT(*) as cnt, MIN(id) as keep_id,
               GROUP_CONCAT(id) as all_ids
        FROM review_decisions
        GROUP BY account_id, stock_code, trade_date, decision_type
        HAVING cnt > 1
        ORDER BY cnt DESC
    """).fetchall()

    results = []
    for g in groups:
        stock_code, trade_date, decision_type, account_id, cnt, keep_id, all_ids = g
        ids = [int(x) for x in all_ids.split(",")]
        to_delete = [x for x in ids if x != keep_id]
        results.append({
            "stock_code": stock_code,
            "trade_date": trade_date,
            "decision_type": decision_type,
            "account_id": account_id,
            "count": cnt,
            "keep_id": keep_id,
            "to_delete": to_delete,
        })
    return results


def print_analysis(dups: list[dict]) -> None:
    """打印分析结果"""
    print(f"\n{'='*80}")
    print(f"review_decisions 冗余记录分析")
    print(f"{'='*80}")
    print(f"数据库: {_DB_PATH}")

    total = conn.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0]
    total_to_delete = sum(len(d["to_delete"]) for d in dups)
    print(f"当前总记录数: {total}")
    print(f"重复组数: {len(dups)}")
    print(f"待删除记录数: {total_to_delete}")
    print(f"清理后保留: {total - total_to_delete}")
    print()

    if dups:
        print(f"{'股票':<10} {'日期':<12} {'决策类型':<28} {'冗余数':>5} {'保留ID':>7} {'删除IDs'}")
        print("-" * 80)
        for d in dups:
            del_ids_str = ",".join(str(x) for x in d["to_delete"])
            print(f"{d['stock_code']:<10} {d['trade_date']:<12} {d['decision_type']:<28} "
                  f"{d['count']-1:>5} {d['keep_id']:>7} {del_ids_str}")

    print()


def show_details(conn: sqlite3.Connection, dups: list[dict]) -> None:
    """展示将被删除的记录详情"""
    for d in dups:
        print(f"\n--- {d['stock_code']} {d['trade_date']} {d['decision_type']} (保留 id={d['keep_id']}) ---")
        for del_id in d["to_delete"]:
            row = conn.execute(
                "SELECT * FROM review_decisions WHERE id=?", (del_id,)
            ).fetchone()
            if row:
                reason = row[6] or ""
                print(f"  ❌ id={del_id} reason={reason[:100]}")


def do_cleanup(conn: sqlite3.Connection, dups: list[dict]) -> int:
    """执行清理，返回删除的记录数"""
    total_deleted = 0
    for d in dups:
        for del_id in d["to_delete"]:
            conn.execute("DELETE FROM review_decisions WHERE id=?", (del_id,))
            total_deleted += 1
    conn.commit()
    return total_deleted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="清理 review_decisions 表中的重复冗余记录 (TASK-20260702-2004-005)"
    )
    parser.add_argument("--commit", action="store_true", help="真正执行删除（默认为 dry-run）")
    parser.add_argument("--show", action="store_true", help="显示将被删除记录的详细内容")
    parser.add_argument("--db", default=str(_DB_PATH), help=f"数据库路径（默认: {_DB_PATH}）")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"错误: 数据库不存在: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))

    try:
        # 检查表是否存在
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='review_decisions'"
        ).fetchone()
        if not table_check:
            print("review_decisions 表不存在，无需清理。")
            sys.exit(0)

        dups = analyze_duplicates(conn)
        print_analysis(dups)

        if not dups:
            print("✅ 当前无重复记录，无需清理。")
            sys.exit(0)

        if args.show:
            show_details(conn, dups)

        if args.commit:
            print(f"⚠️  即将删除 {sum(len(d['to_delete']) for d in dups)} 条重复记录...")
            deleted = do_cleanup(conn, dups)
            print(f"✅ 已删除 {deleted} 条重复记录。")

            # 验证
            remaining = conn.execute("SELECT COUNT(*) FROM review_decisions").fetchone()[0]
            print(f"✅ 清理后记录数: {remaining}")

            # VACUUM 回收空间
            conn.execute("VACUUM")
            print("✅ VACUUM 完成，空间已回收。")
        else:
            total_to_delete = sum(len(d["to_delete"]) for d in dups)
            print(f"\n🔍 DRY-RUN 模式 — 未实际删除。")
            print(f"   如需执行清理，请运行: python scripts/cleanup_review_decisions.py --commit")
    finally:
        conn.close()
