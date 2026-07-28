"""REQ-069: 买入后 total_value = cash + Σmv，不得把 total 当现金扣。"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sim_executor", ROOT / "scripts" / "sim_executor.py"
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_recalc_account_total_cash_plus_mv(tmp_path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE sim_account (id INTEGER PRIMARY KEY, cash REAL, total_value REAL)")
    conn.execute(
        "CREATE TABLE sim_positions (account_id INTEGER, stock_code TEXT, quantity INTEGER, market_value REAL)"
    )
    conn.execute("INSERT INTO sim_account VALUES (1, 50000, 50000)")
    conn.execute("INSERT INTO sim_positions VALUES (1, '000001', 100, 1000)")
    conn.execute("INSERT INTO sim_positions VALUES (1, '000002', 200, 2000)")
    total = mod._recalc_account_total(conn, 1)
    conn.commit()
    assert total == 53000.0
    row = conn.execute("SELECT total_value FROM sim_account WHERE id=1").fetchone()
    assert row[0] == 53000.0
    conn.close()


def test_daily_close_snapshot_fallback_mv():
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location("daily_close_report", ROOT / "scripts" / "daily_close_report.py")
    assert spec and spec.loader
    dcr = module_from_spec(spec)
    spec.loader.exec_module(dcr)

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE sim_account (id INTEGER PRIMARY KEY, cash REAL, total_value REAL, initial_cash REAL, name TEXT)"
    )
    conn.execute(
        "CREATE TABLE sim_positions ("
        "account_id INTEGER, stock_code TEXT, quantity INTEGER, "
        "market_value REAL, current_price REAL, avg_cost REAL)"
    )
    conn.execute("INSERT INTO sim_account VALUES (1, 90000, 90000, 100000, 'learn')")
    # dirty market_value=0 but has price
    conn.execute("INSERT INTO sim_positions VALUES (1, '002709', 100, 0, 37.5, 37.0)")
    snap = dcr.compute_account_snapshot(conn, 1)
    assert snap["market_value"] == 3750.0
    assert snap["total"] == 93750.0
    conn.close()
