import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sim_executor  # noqa: E402


def _make_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sim_account (id INTEGER PRIMARY KEY, cash REAL, total_value REAL, initial_cash REAL)")
    conn.execute("CREATE TABLE sim_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, trade_date TEXT, trade_time TEXT, stock_code TEXT, stock_name TEXT, direction TEXT, price REAL, quantity INTEGER, amount REAL, commission REAL)")
    conn.execute("CREATE TABLE sim_positions (account_id INTEGER, stock_code TEXT, quantity INTEGER)")
    conn.execute("CREATE TABLE review_decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, stock_code TEXT, decision_type TEXT, allowed INTEGER, reason TEXT, created_at TEXT)")
    conn.execute("INSERT INTO sim_account (id, cash, total_value, initial_cash) VALUES (1, 100000, 100000, 100000)")
    conn.commit()
    return conn


def test_daily_buy_amount_budget_blocks_when_today_cap_exceeded(tmp_path):
    db = tmp_path / "sim.db"
    conn = _make_db(db)
    old_db = sim_executor._DB_PATH
    old_amount = sim_executor.MAX_DAILY_BUY_AMOUNT
    old_pct = sim_executor.MAX_DAILY_BUY_PCT
    old_cd = sim_executor.BUY_COOLDOWN_MINUTES
    try:
        sim_executor._DB_PATH = str(db)
        sim_executor.MAX_DAILY_BUY_AMOUNT = 30000.0
        sim_executor.MAX_DAILY_BUY_PCT = 0.35
        sim_executor.BUY_COOLDOWN_MINUTES = 0
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute("INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, direction, amount) VALUES (1, ?, '10:00:00', '000001', 'BUY', 29000)", (today,))
        conn.commit()

        ok, reason, status = sim_executor._check_daily_buy_controls(conn, 1, "000002", 2000)
        assert not ok
        assert "日内买入预算不足" in reason
        assert status["remaining"] == 1000.0
    finally:
        conn.close()
        sim_executor._DB_PATH = old_db
        sim_executor.MAX_DAILY_BUY_AMOUNT = old_amount
        sim_executor.MAX_DAILY_BUY_PCT = old_pct
        sim_executor.BUY_COOLDOWN_MINUTES = old_cd


def test_buy_cooldown_blocks_back_to_back_auto_buys(tmp_path):
    db = tmp_path / "sim.db"
    conn = _make_db(db)
    old_db = sim_executor._DB_PATH
    old_amount = sim_executor.MAX_DAILY_BUY_AMOUNT
    old_pct = sim_executor.MAX_DAILY_BUY_PCT
    old_cd = sim_executor.BUY_COOLDOWN_MINUTES
    try:
        sim_executor._DB_PATH = str(db)
        sim_executor.MAX_DAILY_BUY_AMOUNT = 30000.0
        sim_executor.MAX_DAILY_BUY_PCT = 0.35
        sim_executor.BUY_COOLDOWN_MINUTES = 30
        now = datetime.now()
        conn.execute(
            "INSERT INTO sim_trades (account_id, trade_date, trade_time, stock_code, direction, amount) VALUES (1, ?, ?, '000001', 'BUY', 5000)",
            (now.strftime("%Y-%m-%d"), (now - timedelta(minutes=10)).strftime("%H:%M:%S")),
        )
        conn.commit()

        ok, reason, status = sim_executor._check_daily_buy_controls(conn, 1, "000002", 2000)
        assert not ok
        assert "连续买入冷静期未过" in reason
        assert status["last_buy_code"] == "000001"
    finally:
        conn.close()
        sim_executor._DB_PATH = old_db
        sim_executor.MAX_DAILY_BUY_AMOUNT = old_amount
        sim_executor.MAX_DAILY_BUY_PCT = old_pct
        sim_executor.BUY_COOLDOWN_MINUTES = old_cd
