"""
test_cooldown_dedup.py — TASK-20260702-2004-005 测试
======================================================================
验证 _write_review_decision() 的去重/限流机制。
"""
import os
import sys
import sqlite3
import tempfile
import json
from pathlib import Path
from datetime import datetime

# Setup: point to temp db
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def test_dedup_cooldown_guard():
    """测试：同日同股同类型的 daily_buy_budget_guard 去重"""
    import tempfile
    fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    tmp_path_obj = Path(tmp_path)

    try:
        # Create DB with review_decisions table
        conn = sqlite3.connect(str(tmp_path_obj))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                stock_code TEXT NOT NULL,
                trade_date DATE NOT NULL DEFAULT (date('now', 'localtime')),
                decision_type TEXT NOT NULL,
                allowed INTEGER NOT NULL,
                reason TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.close()

        # Mock: point _DB_PATH to temp db
        import scripts.sim_executor as executor
        os.environ['QUANT_DB_PATH'] = str(tmp_path_obj)
        executor._DB_PATH = str(tmp_path_obj)

        # Simulate: write same cooldown guard 4 times (should only keep 1)
        executor._write_review_decision(1, '002709', 'daily_buy_budget_guard', 0,
                                         '连续买入冷静期未过：距上次买入 0 分钟 < 30 分钟')
        executor._write_review_decision(1, '002709', 'daily_buy_budget_guard', 0,
                                         '连续买入冷静期未过：距上次买入 1 分钟 < 30 分钟')
        executor._write_review_decision(1, '002709', 'daily_buy_budget_guard', 0,
                                         '连续买入冷静期未过：距上次买入 2 分钟 < 30 分钟')
        executor._write_review_decision(1, '002709', 'daily_buy_budget_guard', 0,
                                         '连续买入冷静期未过：距上次买入 3 分钟 < 30 分钟')

        # Verify: only 1 record
        conn = sqlite3.connect(str(tmp_path_obj))
        rows = conn.execute(
            "SELECT * FROM review_decisions WHERE stock_code='002709' AND decision_type='daily_buy_budget_guard'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1, f"期望 1 条记录，实际 {len(rows)} 条"
        assert rows[0][4] == 'daily_buy_budget_guard'
        assert rows[0][5] == 0
        print(f"✅ test_dedup_cooldown_guard PASSED: 4次写入 -> {len(rows)}条记录")

    finally:
        # Cleanup
        tmp_path_obj.unlink(missing_ok=True)
        os.environ.pop('_write_review_decision_test_overrides', None)


def test_dedup_daily_new_position_limit():
    """测试：同日同股同类型的 daily_new_position_limit 去重"""
    import tempfile
    fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    tmp_path_obj = Path(tmp_path)

    try:
        conn = sqlite3.connect(str(tmp_path_obj))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                stock_code TEXT NOT NULL,
                trade_date DATE NOT NULL DEFAULT (date('now', 'localtime')),
                decision_type TEXT NOT NULL,
                allowed INTEGER NOT NULL,
                reason TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.close()

        import scripts.sim_executor as executor
        os.environ['QUANT_DB_PATH'] = str(tmp_path_obj)
        executor._DB_PATH = str(tmp_path_obj)

        executor._write_review_decision(1, '000001', 'daily_new_position_limit', 0, '今日新建仓位已达上限')
        executor._write_review_decision(1, '000001', 'daily_new_position_limit', 0, '今日新建仓位已达上限（重复）')

        conn = sqlite3.connect(str(tmp_path_obj))
        rows = conn.execute(
            "SELECT * FROM review_decisions WHERE stock_code='000001' AND decision_type='daily_new_position_limit'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1, f"期望 1 条记录，实际 {len(rows)} 条"
        print(f"✅ test_dedup_daily_new_position_limit PASSED: 2次写入 -> {len(rows)}条记录")

    finally:
        tmp_path_obj.unlink(missing_ok=True)
        os.environ.pop('_write_review_decision_test_overrides', None)


def test_different_decisions_kept_separately():
    """测试：不同 decision_type 不会相互去重"""
    import tempfile
    fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    tmp_path_obj = Path(tmp_path)

    try:
        conn = sqlite3.connect(str(tmp_path_obj))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                stock_code TEXT NOT NULL,
                trade_date DATE NOT NULL DEFAULT (date('now', 'localtime')),
                decision_type TEXT NOT NULL,
                allowed INTEGER NOT NULL,
                reason TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.close()

        import scripts.sim_executor as executor
        os.environ['QUANT_DB_PATH'] = str(tmp_path_obj)
        executor._DB_PATH = str(tmp_path_obj)

        # Write different decision types for same stock same day
        executor._write_review_decision(1, '000600', 'daily_buy_budget_guard', 0, '冷静期未过')
        executor._write_review_decision(1, '000600', 'position_count_limit', 0, '持仓数超限')
        executor._write_review_decision(1, '000600', 'daily_buy_budget_guard', 0, '冷静期未过重复')

        conn = sqlite3.connect(str(tmp_path_obj))
        total = conn.execute("SELECT COUNT(*) FROM review_decisions WHERE stock_code='000600'").fetchone()[0]
        guard_cnt = conn.execute(
            "SELECT COUNT(*) FROM review_decisions WHERE stock_code='000600' AND decision_type='daily_buy_budget_guard'"
        ).fetchone()[0]
        pos_cnt = conn.execute(
            "SELECT COUNT(*) FROM review_decisions WHERE stock_code='000600' AND decision_type='position_count_limit'"
        ).fetchone()[0]
        conn.close()

        assert total == 2, f"期望总共2条，实际{total}条"
        assert guard_cnt == 1, f"期望 guard 1条，实际{guard_cnt}条"
        assert pos_cnt == 1, f"期望 position 1条，实际{pos_cnt}条"
        print(f"✅ test_different_decisions_kept_separately PASSED: total={total}, guard={guard_cnt}, pos={pos_cnt}")

    finally:
        tmp_path_obj.unlink(missing_ok=True)
        os.environ.pop('_write_review_decision_test_overrides', None)


def test_dedup_after_cleanup():
    """验证清理后 DB 没有重复记录"""
    db_path = ROOT / "data" / "sim_live_mirror.db"
    if not db_path.exists():
        print("⚠️ test_dedup_after_cleanup SKIPPED: DB not found")
        return

    conn = sqlite3.connect(str(db_path))
    dups = conn.execute("""
        SELECT stock_code, trade_date, decision_type, COUNT(*) as cnt
        FROM review_decisions
        GROUP BY account_id, stock_code, trade_date, decision_type
        HAVING cnt > 1
    """).fetchall()
    conn.close()

    assert len(dups) == 0, f"清理后仍有 {len(dups)} 组重复: {dups[:5]}"
    print(f"✅ test_dedup_after_cleanup PASSED: 0 组重复记录")


if __name__ == "__main__":
    print("=" * 60)
    print("TASK-20260702-2004-005 去重/限流测试")
    print("=" * 60)
    print()

    tests = [
        ("去重：冷静期拒绝型", test_dedup_cooldown_guard),
        ("去重：仓位上限拒绝型", test_dedup_daily_new_position_limit),
        ("去重：不同类型互不影响", test_different_decisions_kept_separately),
        ("验证：清理后无重复", test_dedup_after_cleanup),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"❌ {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print()
    print(f"结果: {passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)
