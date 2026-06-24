"""
tests/test_buy_risk_guard.py
REQ-028 买入防接飞刀风控 — 单元测试（重构版：使用正确 sim_ 表名 + 列名）
"""
from datetime import date, datetime
from types import SimpleNamespace
import sqlite3
import tempfile
import os

from vqlearn.services.buy_risk_guard import (
    RiskDecision,
    evaluate_buy_risk_guard,
    evaluate_market_panic,
    evaluate_opening_crash_filter,
    check_position_limit,
    check_daily_trade_limit,
    check_position_count_limit,
    check_daily_new_position_limit,
    evaluate_buy_risk_with_limits,
)


def create_test_db():
    """创建测试数据库（使用正确的 sim_ 表名 + 列名），返回 db_path。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    # sim_account（注意列名：total_value，不是 total_assets）
    cursor.execute("""CREATE TABLE sim_account (
        id INTEGER PRIMARY KEY,
        account_name TEXT,
        initial_cash REAL,
        cash REAL,
        total_value REAL,
        created_at TEXT,
        updated_at TEXT
    )""")
    # sim_positions（注意列名：quantity，不是 volume；avg_cost，不是 cost）
    cursor.execute("""CREATE TABLE sim_positions (
        id INTEGER PRIMARY KEY,
        account_id INTEGER,
        stock_code TEXT,
        stock_name TEXT,
        quantity INTEGER,
        avg_cost REAL,
        current_price REAL,
        market_value REAL,
        pnl REAL,
        pnl_pct REAL,
        updated_at TEXT
    )""")
    # sim_trades（注意列名：direction，不是 action；trade_date，不是 date）
    cursor.execute("""CREATE TABLE sim_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER,
        trade_date TEXT,
        trade_time TEXT,
        stock_code TEXT,
        stock_name TEXT,
        direction TEXT,
        price REAL,
        quantity INTEGER,
        amount REAL,
        commission REAL
    )""")
    # 插入测试账户：total_value = 200000
    cursor.execute(
        "INSERT INTO sim_account (id, account_name, initial_cash, cash, total_value, created_at, updated_at) "
        "VALUES (1, 'test', 200000, 100000, 200000, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
    )
    conn.commit()
    conn.close()
    return path


def cleanup_test_db(path):
    if os.path.exists(path):
        os.remove(path)


def test_market_panic_by_index_drop():
    d = evaluate_market_panic(index_changes_pct={"上证指数": -1.2})
    assert d.blocked is True
    assert "大盘情绪熔断" in d.reason
    assert d.details["trigger"] == "index"


def test_market_not_panic():
    d = evaluate_market_panic(index_changes_pct={"上证指数": -0.5}, declining_count=3000, total_count=5000)
    assert d.blocked is False


def test_opening_crash_filter_blocks_when_drop_volume_and_break_support():
    d = evaluate_opening_crash_filter(
        code="600000",
        current_price=9.2,
        open_price=9.4,
        prev_close=10.0,
        low_price=9.1,
        support_level=9.3,
        current_volume=2_000_000,
        avg_vol_5d=10_000_000,
        now=datetime(2026, 5, 26, 9, 40),
    )
    assert d.blocked is True
    assert "单票暴跌禁买" in d.reason


def test_opening_crash_filter_does_not_block_without_volume_spike():
    d = evaluate_opening_crash_filter(
        code="600000",
        current_price=9.2,
        open_price=9.4,
        prev_close=10.0,
        low_price=9.1,
        support_level=9.3,
        current_volume=100_000,
        avg_vol_5d=10_000_000,
        now=datetime(2026, 5, 26, 9, 40),
    )
    assert d.blocked is False
    assert "未放量" in d.reason


def test_buy_risk_guard_blocks_market_before_single_stock():
    tick = SimpleNamespace(last_price=9.2, open_price=9.4, pre_close=10.0, low_price=9.1, volume=2_000_000)

    def panic_fetcher():
        return RiskDecision(True, "大盘情绪熔断：测试", {"trigger": "index"})

    d = evaluate_buy_risk_guard(
        code="600000",
        tick=tick,
        db_path=None,  # 不检查持仓上限
        account_id=1,
        prev_close=10.0,
        support_level=9.3,
        avg_vol_5d=10_000_000,
        market_fetcher=panic_fetcher,
    )
    assert d.blocked is True
    assert d.reason.startswith("大盘情绪熔断")


def test_check_position_limit_blocks_when_exceeds_max():
    """测试持仓超过上限时被阻止"""
    db_path = create_test_db()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 插入现有持仓：600000 40000 股，成本价 10 元 → 市值 400000
        # 总资产 200000，但持仓市值 400000，已经超过 20% 上限
        cursor.execute(
            "INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct, updated_at) "
            "VALUES (1, '600000', '测试', 40000, 10.0, 10.0, 400000, 0, 0, '2026-01-01 00:00:00')"
        )
        conn.commit()
        conn.close()

        d = check_position_limit(
            db_path=db_path,
            account_id=1,
            code="600000",
            max_position_pct=0.20,
            current_price=10.0,
            additional_shares=100,
        )
        assert d.blocked is True
        assert "持仓超限" in d.reason
        assert d.details["trigger"] == "position_limit"
    finally:
        cleanup_test_db(db_path)


def test_check_position_limit_passes_when_under_max():
    """测试持仓未超过上限时通过"""
    db_path = create_test_db()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 插入现有持仓：600000 1000 股，成本价 10 元 → 市值 10000
        # 总资产 200000，持仓占比 5%，低于 20% 上限
        cursor.execute(
            "INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct, updated_at) "
            "VALUES (1, '600000', '测试', 1000, 10.0, 10.0, 10000, 0, 0, '2026-01-01 00:00:00')"
        )
        conn.commit()
        conn.close()

        d = check_position_limit(
            db_path=db_path,
            account_id=1,
            code="600000",
            max_position_pct=0.20,
            current_price=10.0,
            additional_shares=100,
        )
        assert d.blocked is False
        assert "仓位检查通过" in d.reason
    finally:
        cleanup_test_db(db_path)


def test_check_daily_trade_limit_blocks_when_exceeds_max():
    """测试单日交易笔数超过上限时被阻止"""
    db_path = create_test_db()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        today = str(date.today())
        # 插入 10 笔买入交易（达到上限）
        for i in range(10):
            cursor.execute(
                "INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, stock_name, direction, price, quantity, amount, commission) "
                "VALUES (1, ?, '09:30:00', '600000', '测试', 'BUY', 10.0, 100, 1000, 5.0)",
                (today,)
            )
        conn.commit()
        conn.close()

        d = check_daily_trade_limit(
            db_path=db_path,
            account_id=1,
            trade_date=today,
            max_daily_trades=10,
        )
        assert d.blocked is True
        assert "单日交易超限" in d.reason
    finally:
        cleanup_test_db(db_path)


def test_check_daily_trade_limit_passes_when_under_max():
    """测试单日交易笔数未超过上限时通过"""
    db_path = create_test_db()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        today = str(date.today())
        # 插入 5 笔买入交易（低于上限 10）
        for i in range(5):
            cursor.execute(
                "INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, stock_name, direction, price, quantity, amount, commission) "
                "VALUES (1, ?, '09:30:00', '600000', '测试', 'BUY', 10.0, 100, 1000, 5.0)",
                (today,)
            )
        conn.commit()
        conn.close()

        d = check_daily_trade_limit(
            db_path=db_path,
            account_id=1,
            trade_date=today,
            max_daily_trades=10,
        )
        assert d.blocked is False
        assert "单日交易检查通过" in d.reason
    finally:
        cleanup_test_db(db_path)


def test_evaluate_buy_risk_with_limits_all_passing():
    """测试 evaluate_buy_risk_with_limits 全通场景"""
    db_path = create_test_db()
    try:
        tick = SimpleNamespace(last_price=10.0, open_price=10.0, pre_close=10.0, low_price=10.0, volume=1_000_000)

        # 清除大盘熔断缓存，确保 mock 生效
        import vqlearn.services.buy_risk_guard as _mod
        _mod._MARKET_CACHE = None

        d = evaluate_buy_risk_with_limits(
            code="600000",
            tick=tick,
            db_path=db_path,
            account_id=1,
            prev_close=10.0,
            support_level=9.0,
            avg_vol_5d=1_000_000,
            max_position_pct=0.20,
            max_daily_trades=10,
            max_positions=6,
            max_daily_new=3,
            additional_shares=100,
        )
        assert d.blocked is False, f"期望通过，实际: {d.reason}"
        assert "全部通过" in d.reason
    finally:
        cleanup_test_db(db_path)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "-s"])
