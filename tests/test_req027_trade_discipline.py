import sqlite3

from sim.discipline import (
    ensure_trade_discipline_tables,
    get_discipline_plan,
    render_discipline_score,
    score_trade_discipline,
    upsert_discipline_plan,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE sim_account (id INTEGER PRIMARY KEY, cash REAL, total_value REAL)")
    conn.execute(
        """CREATE TABLE sim_positions (
        id INTEGER PRIMARY KEY, account_id INTEGER, stock_code TEXT, stock_name TEXT,
        market_value REAL
    )"""
    )
    conn.execute(
        """CREATE TABLE sim_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, trade_date TEXT,
        stock_code TEXT, stock_name TEXT, direction TEXT, price REAL, quantity INTEGER,
        amount REAL, signal_reason TEXT, signal_detail TEXT, trade_context TEXT
    )"""
    )
    ensure_trade_discipline_tables(conn)
    return conn


def test_checkin_plan_is_persisted_and_loaded():
    conn = _conn()
    plan = upsert_discipline_plan(
        conn,
        1,
        "2026-06-01",
        max_daily_trades=3,
        max_buy_trades=1,
        min_cash_pct=20,
        max_turnover_pct=30,
        notes="只做计划内交易",
    )

    loaded = get_discipline_plan(conn, 1, "2026-06-01")
    assert plan.max_daily_trades == 3
    assert loaded.max_buy_trades == 1
    assert loaded.min_cash_pct == 0.20
    assert loaded.max_turnover_pct == 0.30
    assert loaded.notes == "只做计划内交易"


def test_score_penalizes_trade_count_cash_and_chase():
    conn = _conn()
    conn.execute("INSERT INTO sim_account (id, cash, total_value) VALUES (1, 5000, 100000)")
    conn.execute(
        "INSERT INTO sim_positions (account_id, stock_code, stock_name, market_value) VALUES (1,'000001','平安银行',50000)"
    )
    for code in ["000001", "000002", "000003"]:
        conn.execute(
            """INSERT INTO sim_trades
            (account_id, trade_date, stock_code, stock_name, direction, price, quantity, amount, signal_reason)
            VALUES (1,'2026-06-01',?,?,'BUY',10,1000,10000,'追高临时起意')""",
            (code, code),
        )
    upsert_discipline_plan(
        conn,
        1,
        "2026-06-01",
        max_daily_trades=2,
        max_buy_trades=2,
        min_cash_pct=10,
        max_single_position_pct=35,
        max_turnover_pct=20,
    )

    result = score_trade_discipline(conn, 1, "2026-06-01", persist=True)
    rules = {v["rule"] for v in result["violations"]}

    assert result["score"] < 100
    assert "max_daily_trades" in rules
    assert "max_buy_trades" in rules
    assert "min_cash_pct" in rules
    assert "max_single_position_pct" in rules
    assert "max_turnover_pct" in rules
    assert "no_chase" in rules
    assert conn.execute("SELECT score FROM trade_discipline_scores WHERE account_id=1 AND trade_date='2026-06-01'").fetchone()[0] == result["score"]


def test_render_contains_plan_and_execution_summary():
    conn = _conn()
    conn.execute("INSERT INTO sim_account (id, cash, total_value) VALUES (1, 90000, 100000)")
    result = score_trade_discipline(conn, 1, "2026-06-01", persist=False)
    md = render_discipline_score(result)

    assert "交易纪律打卡" in md
    assert "知行合一评分" in md
    assert "盘前纪律" in md
    assert "盘后执行" in md
    assert "未发现明显偏差" in md
