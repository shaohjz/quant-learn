"""Pytest path bootstrap and common fixtures.

QL-002 changes:
  - Root path bootstrap for imports
  - temp_db fixture: creates a temporary SQLite DB with proper schema
  - marker registration for integration/qmt
"""

from __future__ import annotations

import sys
import tempfile
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)


# ─── Marker registration (for pyproject.toml-based config) ───
def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires external services/network")
    config.addinivalue_line("markers", "qmt: requires QMT/xtquant environment (Windows + Python 3.11)")


# ─── Temporary DB fixture ───
@pytest.fixture
def temp_db(tmp_path):
    """Provide a temporary SQLite database with the sim schema initialized.

    Yields the Path to the .db file. Tests should inject this path
    instead of using the real data/*.db files.
    """
    db_path = tmp_path / "test_sim.db"
    conn = sqlite3.connect(str(db_path))
    # Initialize minimal schema needed for tests
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sim_account (
            id INTEGER PRIMARY KEY,
            account_name TEXT,
            initial_cash REAL DEFAULT 200000.0,
            cash REAL,
            total_value REAL,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sim_positions (
            id INTEGER PRIMARY KEY,
            account_id INTEGER DEFAULT 1,
            stock_code TEXT,
            stock_name TEXT,
            quantity INTEGER,
            avg_cost REAL,
            current_price REAL DEFAULT 0,
            market_value REAL DEFAULT 0,
            pnl REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            trailing_stop_price REAL,
            highest_price REAL,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sim_trades (
            id INTEGER PRIMARY KEY,
            account_id INTEGER DEFAULT 1,
            trade_date TEXT,
            stock_code TEXT,
            stock_name TEXT,
            direction TEXT,
            price REAL,
            quantity INTEGER,
            amount REAL,
            commission REAL DEFAULT 0,
            tax REAL DEFAULT 0,
            signal_reason TEXT,
            broker TEXT DEFAULT 'sim',
            broker_order_id TEXT,
            created_at TEXT,
            signal_detail TEXT,
            trade_time TEXT,
            trade_context TEXT
        );
        CREATE TABLE IF NOT EXISTS sim_daily_nav (
            id INTEGER PRIMARY KEY,
            account_id INTEGER DEFAULT 1,
            trade_date TEXT,
            total_value REAL,
            cash REAL,
            market_value REAL,
            daily_return REAL,
            cumulative_return REAL,
            max_drawdown REAL,
            created_at TEXT,
            cash_jump_detected INTEGER DEFAULT 0,
            cash_jump_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS sim_orders (
            id INTEGER PRIMARY KEY,
            account_id INTEGER DEFAULT 1,
            order_id TEXT,
            stock_code TEXT,
            stock_name TEXT,
            direction TEXT,
            offset TEXT,
            price REAL,
            quantity INTEGER,
            traded INTEGER DEFAULT 0,
            status TEXT,
            order_time TEXT,
            broker TEXT,
            broker_order_id TEXT UNIQUE,
            strategy_name TEXT,
            signal_reason TEXT
        );
        CREATE TABLE IF NOT EXISTS sim_fills (
            id INTEGER PRIMARY KEY,
            account_id INTEGER DEFAULT 1,
            order_id TEXT,
            stock_code TEXT,
            stock_name TEXT,
            direction TEXT,
            trade_price REAL,
            trade_volume INTEGER,
            trade_amount REAL,
            commission REAL,
            tax REAL,
            trade_time TEXT,
            broker TEXT,
            broker_trade_id TEXT,
            strategy_name TEXT
        );
        CREATE TABLE IF NOT EXISTS sim_account_events (
            id INTEGER PRIMARY KEY,
            account_id INTEGER DEFAULT 1,
            event_type TEXT,
            event_date TEXT,
            old_value REAL,
            new_value REAL,
            description TEXT,
            created_at TEXT
        );
    """)
    # Insert default account
    conn.execute(
        "INSERT INTO sim_account (id, account_name, initial_cash, cash, total_value, created_at, updated_at) "
        "VALUES (1, 'learn', 200000.0, 200000.0, 200000.0, '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()
    yield db_path
