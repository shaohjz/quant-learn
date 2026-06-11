"""REQ-041: 智能跟踪止损。"""

import sqlite3


def _init_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sim_account (id INTEGER PRIMARY KEY, cash REAL, total_value REAL, updated_at TEXT)")
    conn.execute(
        """
        CREATE TABLE sim_positions (
            account_id INTEGER, stock_code TEXT, stock_name TEXT,
            quantity INTEGER, avg_cost REAL, current_price REAL,
            market_value REAL, pnl REAL, pnl_pct REAL
        )
        """
    )
    conn.execute("INSERT INTO sim_account (id, cash, total_value) VALUES (1, 10000, 10000)")
    conn.execute(
        """
        INSERT INTO sim_positions
        (account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl, pnl_pct)
        VALUES (1, '000001', '测试股', 100, 10.0, 10.0, 1000, 0, 0)
        """
    )
    conn.commit()
    conn.close()


def test_calc_trailing_stop_ladders_and_never_moves_down():
    from scripts.sim_executor import calc_trailing_stop

    assert calc_trailing_stop(10.0, 10.4, None)[0] == 0.0
    assert calc_trailing_stop(10.0, 10.6, None)[0] == 10.0
    assert calc_trailing_stop(10.0, 11.2, None)[0] == 10.2
    assert calc_trailing_stop(10.0, 12.5, None)[0] == 11.5  # max(11.0, 12.5*0.92)
    assert calc_trailing_stop(10.0, 11.0, 11.5)[0] == 11.5  # 不下移


def test_update_position_trailing_adds_missing_columns_and_updates(tmp_path, monkeypatch):
    import scripts.sim_executor as ex

    db = tmp_path / "sim.db"
    _init_db(db)
    monkeypatch.setattr(ex, "_DB_PATH", str(db))

    res = ex.update_position_trailing(1, "000001", 11.2)

    assert res["updated"] is True
    assert round(res["highest"], 2) == 11.2
    assert round(res["trailing"], 2) == 10.2

    conn = sqlite3.connect(db)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sim_positions)")}
        row = conn.execute(
            "SELECT highest_price, trailing_stop_price FROM sim_positions WHERE stock_code='000001'"
        ).fetchone()
    finally:
        conn.close()

    assert "highest_price" in cols
    assert "trailing_stop_price" in cols
    assert round(row[0], 2) == 11.2
    assert round(row[1], 2) == 10.2


def test_update_all_positions_market_value_uses_trailing_stop(tmp_path, monkeypatch):
    import scripts.sim_executor as ex

    db = tmp_path / "sim.db"
    _init_db(db)
    monkeypatch.setattr(ex, "_DB_PATH", str(db))
    monkeypatch.setattr(ex, "_ACCOUNT_ID", 1)

    count = ex.update_all_positions_market_value({"000001": 12.5})

    assert count == 1
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT current_price, highest_price, trailing_stop_price, pnl_pct FROM sim_positions WHERE stock_code='000001'"
        ).fetchone()
    finally:
        conn.close()

    assert row[0] == 12.5
    assert row[1] == 12.5
    assert round(row[2], 2) == 11.5
    assert round(row[3], 1) == 25.0
