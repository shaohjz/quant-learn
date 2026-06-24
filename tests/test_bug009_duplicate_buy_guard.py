"""BUG-009: 同一股票同日多信号不应重复买入。"""

import sqlite3
from datetime import datetime


def _init_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sim_account (id INTEGER PRIMARY KEY, cash REAL, total_value REAL)"
    )
    conn.execute(
        """
        CREATE TABLE sim_positions (
            account_id INTEGER, stock_code TEXT, stock_name TEXT,
            quantity INTEGER, avg_cost REAL, current_price REAL,
            market_value REAL, pnl REAL, pnl_pct REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER, trade_date TEXT, trade_time TEXT,
            stock_code TEXT, stock_name TEXT, direction TEXT,
            price REAL, quantity INTEGER, amount REAL, commission REAL
        )
        """
    )
    conn.execute(
        "CREATE TABLE review_decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, stock_code TEXT, decision_type TEXT, action INTEGER, reason TEXT, created_at TEXT)"
    )
    conn.execute("INSERT INTO sim_account (id, cash, total_value) VALUES (1, 50000, 50000)")
    conn.commit()
    conn.close()


def test_execute_trade_skips_duplicate_buy_same_day(tmp_path, monkeypatch):
    import scripts.sim_executor as ex

    db = tmp_path / "sim.db"
    _init_db(db)
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO sim_trades
        (account_id, trade_date, trade_time, stock_code, stock_name, direction, price, quantity, amount, commission)
        VALUES (1, ?, '09:30:00', '002709', '天赐材料', 'BUY', 10.0, 100, 1000, 5)
        """,
        (today,),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(ex, "_DB_PATH", str(db))
    monkeypatch.setattr(ex, "_ACCOUNT_ID", 1)
    monkeypatch.setattr(ex, "decide_action", lambda rule, cur_price, **kw: "BUY")

    result = ex.execute_trade({"code": "002709", "name": "天赐材料", "level": "buy_strong"}, 10.0)

    assert result["action"] == "NO_ACTION"
    assert result["success"] is True
    assert "今日已买入过" in result["message"]

    conn = sqlite3.connect(db)
    try:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM sim_trades WHERE account_id=1 AND stock_code='002709' AND direction='BUY'"
        ).fetchone()[0]
        decision = conn.execute(
            "SELECT decision_type, action, reason FROM review_decisions WHERE stock_code='002709'"
        ).fetchone()
    finally:
        conn.close()

    assert cnt == 1
    assert decision[0] == "duplicate_buy_guard"
    assert decision[1] == 0
