"""REQ-062: buy_zone/buy_strong 的 signal_reason 必须以建仓价为准，不含文案串价。"""

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
            market_value REAL, pnl REAL, pnl_pct REAL,
            highest_price REAL, trailing_stop_price REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER, trade_date TEXT, trade_time TEXT,
            stock_code TEXT, stock_name TEXT, direction TEXT,
            price REAL, quantity INTEGER, amount REAL, commission REAL,
            signal_reason TEXT
        )
        """
    )
    conn.execute(
        "CREATE TABLE review_decisions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, stock_code TEXT, "
        "trade_date TEXT, decision_type TEXT, allowed INTEGER, reason TEXT, created_at TEXT)"
    )
    conn.execute("INSERT INTO sim_account (id, cash, total_value) VALUES (1, 100000, 100000)")
    conn.commit()
    conn.close()


def test_buy_zone_signal_reason_uses_fill_price(tmp_path, monkeypatch):
    import scripts.sim_executor as ex

    db = tmp_path / "sim.db"
    _init_db(db)
    monkeypatch.setattr(ex, "_DB_PATH", str(db))
    monkeypatch.setattr(ex, "_ACCOUNT_ID", 1)
    # 跳过所有风控，强制 BUY
    monkeypatch.setattr(ex, "decide_action", lambda rule, cur_price, **kw: "BUY")
    monkeypatch.setattr(ex, "_has_today_buy", lambda *a, **k: False)
    monkeypatch.setattr(ex, "_has_today_sell", lambda *a, **k: False)
    monkeypatch.setattr(ex, "_has_recent_stop_loss", lambda *a, **k: False)
    monkeypatch.setattr(ex, "_ensure_trailing_columns", lambda conn: None)

    # 脏文案：跌至 5.31（错误串价），真实建仓 3.86
    rule = {
        "code": "600310",
        "name": "广西能源",
        "level": "buy_zone",
        "trigger": 3.90,
        "message": "💰 广西能源跌至 5.31！接近 MA10(5.31)",
    }
    fill = 3.86
    result = ex.execute_trade(rule, fill)
    assert result["success"] is True
    assert result.get("trade") is not None

    conn = sqlite3.connect(db)
    reason = conn.execute(
        "SELECT signal_reason FROM sim_trades WHERE stock_code='600310' AND direction='BUY'"
    ).fetchone()[0]
    conn.close()

    assert "建仓价=3.86" in reason
    assert "触发阈值=3.90" in reason
    assert "5.31" not in reason  # 脏文案数字不得进入 signal_reason
