from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _make_snapshot_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE sim_account (
            id INTEGER PRIMARY KEY,
            cash REAL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE sim_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            stock_code TEXT,
            quantity INTEGER,
            avg_cost REAL,
            current_price REAL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE daily_snapshot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date DATE NOT NULL UNIQUE,
            account_type TEXT DEFAULT 'sim',
            total_asset REAL,
            total_market_value REAL,
            cash REAL,
            position_count INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute("INSERT INTO sim_account(id, cash) VALUES (1, 1000)")
    cur.executemany(
        """
        INSERT INTO sim_positions(account_id, stock_code, quantity, avg_cost, current_price)
        VALUES (1, ?, ?, ?, ?)
        """,
        [
            ("600001", 10, 8.0, 9.0),
            ("000002", 20, 3.0, 4.0),
            ("000003", 30, 1.5, 0.0),
        ],
    )
    conn.commit()
    conn.close()


def test_snapshot_prefers_market_close_then_db_current_then_avg_cost(tmp_path, monkeypatch):
    import scripts.snapshot_daily as sd

    db = tmp_path / "sim.db"
    _make_snapshot_db(db)
    monkeypatch.setattr(sd, "DB_PATH", db)
    monkeypatch.setattr(sd, "_fetch_close_prices", lambda codes: {"600001": 10.0})

    assert sd.save_snapshot("2026-06-01") is True

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT total_asset, total_market_value, cash, position_count FROM daily_snapshot WHERE snapshot_date='2026-06-01'"
    ).fetchone()
    conn.close()

    # market: 10*10.0 + db current fallback: 20*4.0 + avg cost fallback: 30*1.5
    assert row == (1225.0, 225.0, 1000.0, 3)


def test_fetch_close_prices_filters_invalid_prices(monkeypatch):
    import scripts.snapshot_daily as sd

    def fake_prices(codes):
        return {
            "600001": {"price": "10.5"},
            "000002": {"price": 0},
            "000003": {"price": None},
        }

    monkeypatch.setitem(sys.modules, "sim.realtime_price", type("M", (), {"get_latest_prices_with_fallback": fake_prices}))

    assert sd._fetch_close_prices(["600001", "000002", "000003"]) == {"600001": 10.5}
