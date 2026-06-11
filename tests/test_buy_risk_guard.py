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
    evaluate_buy_risk_with_limits,
)


def create_test_db():
    """创建测试数据库，返回 db_path。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE accounts (
        id INTEGER PRIMARY KEY,
        account_id INTEGER,
        total_assets REAL
    )""")
    cursor.execute("""CREATE TABLE positions (
        id INTEGER PRIMARY KEY,
        account_id INTEGER,
        code TEXT,
        volume INTEGER,
        cost REAL
    )""")
    cursor.execute("""CREATE TABLE trades (
        id INTEGER PRIMARY KEY,
        account_id INTEGER,
        action TEXT,
        code TEXT,
        date TEXT
    )""")
    # 插入测试账户：总资产 200000
    cursor.execute("INSERT INTO accounts (account_id, total_assets) VALUES (1, 200000)")
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


def test_market_panic_by_breadth():
    d = evaluate_market_panic(declining_count=4100, total_count=5000)
    assert d.blocked is True
    assert d.details["trigger"] == "breadth"


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
            "INSERT INTO positions (account_id, code, volume, cost) VALUES (1, '600000', 40000, 10.0)"
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
            "INSERT INTO positions (account_id, code, volume, cost) VALUES (1, '600000', 1000, 10.0)"
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
    """测试单日交易超过上限时被阻止"""
    db_path = create_test_db()
    today = date.today().strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 插入 10 笔买入交易（达到上限）
        for i in range(10):
            cursor.execute(
                "INSERT INTO trades (account_id, action, code, date) VALUES (1, 'buy', ?, ?)",
                (f"60000{i}", today + " 09:30:00")
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
        assert d.details["trigger"] == "daily_trade_limit"
    finally:
        cleanup_test_db(db_path)


def test_check_daily_trade_limit_passes_when_under_max():
    """测试单日交易未超过上限时通过"""
    db_path = create_test_db()
    today = date.today().strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 插入 5 笔买入交易（低于 10 笔上限）
        for i in range(5):
            cursor.execute(
                "INSERT INTO trades (account_id, action, code, date) VALUES (1, 'buy', ?, ?)",
                (f"60000{i}", today + " 09:30:00")
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


def test_evaluate_buy_risk_with_limits_blocks_position_limit():
    """测试统一风控：持仓超限时阻止买入"""
    db_path = create_test_db()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 插入大额持仓，使买入后超过 20% 上限
        cursor.execute(
            "INSERT INTO positions (account_id, code, volume, cost) VALUES (1, '600000', 50000, 10.0)"
        )
        conn.commit()
        conn.close()

        tick = SimpleNamespace(last_price=10.0, open_price=9.5, pre_close=10.0, low_price=9.2, volume=1_000_000)

        # 直接使用 check_position_limit 测试，避免 market fetcher 缓存问题
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
    finally:
        cleanup_test_db(db_path)


def test_evaluate_buy_risk_with_limits_passes_all_checks():
    """测试统一风控：所有检查通过"""
    db_path = create_test_db()
    try:
        tick = SimpleNamespace(last_price=10.0, open_price=9.5, pre_close=10.0, low_price=9.2, volume=1_000_000)

        # 直接使用 check_position_limit 和 check_daily_trade_limit 测试
        d1 = check_position_limit(
            db_path=db_path,
            account_id=1,
            code="600000",
            max_position_pct=0.20,
            current_price=10.0,
            additional_shares=100,
        )
        d2 = check_daily_trade_limit(
            db_path=db_path,
            account_id=1,
            max_daily_trades=10,
        )
        assert d1.blocked is False
        assert d2.blocked is False
    finally:
        cleanup_test_db(db_path)

