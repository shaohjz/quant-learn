"""REQ-058: 清仓后 threshold_state 级联失效 + 巡检全账户。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from sim.sell_signal_audit import expire_thresholds_on_flat, normalize_stock_code
from scripts.patrol_orphan_thresholds import patrol


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE sim_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            stock_code TEXT,
            quantity INTEGER
        );
        CREATE TABLE threshold_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT,
            rule_name TEXT,
            status TEXT,
            notes TEXT,
            updated_at TEXT
        );
        """
    )


def test_normalize_stock_code():
    assert normalize_stock_code("sh600519") == "600519"
    assert normalize_stock_code("002709") == "002709"
    assert normalize_stock_code("2709") == "002709"


def test_expire_thresholds_on_flat(tmp_path: Path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    _schema(conn)
    conn.execute(
        "INSERT INTO threshold_state (stock_code, rule_name, status, notes) "
        "VALUES ('002709', 'trailing_stop', 'pending', '')"
    )
    conn.execute(
        "INSERT INTO threshold_state (stock_code, rule_name, status, notes) "
        "VALUES ('002709', 'buy_zone', 'pending', '')"
    )
    conn.commit()
    n = expire_thresholds_on_flat(conn.cursor(), "002709", note="test-flat")
    conn.commit()
    assert n == 1
    rows = conn.execute(
        "SELECT rule_name, status, notes FROM threshold_state ORDER BY id"
    ).fetchall()
    assert rows[0][1] == "expired"
    assert "test-flat" in (rows[0][2] or "")
    assert rows[1][1] == "pending"  # 买入规则不动
    conn.close()


def test_patrol_cleans_deleted_position_all_accounts(tmp_path: Path):
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    _schema(conn)
    # 账户 3 已 DELETE 持仓；threshold 仍 pending（旧巡检只看 account_id=1 会漏）
    conn.execute(
        "INSERT INTO threshold_state (stock_code, rule_name, status, notes) "
        "VALUES ('300059', 'trailing_stop', 'confirmed', 'hang')"
    )
    # 另一标的仍有持仓，不应被清
    conn.execute(
        "INSERT INTO sim_positions (account_id, stock_code, quantity) "
        "VALUES (1, '601628', 100)"
    )
    conn.execute(
        "INSERT INTO threshold_state (stock_code, rule_name, status, notes) "
        "VALUES ('601628', 'trailing_stop', 'armed', 'keep')"
    )
    conn.commit()
    conn.close()

    cleaned = patrol(db)
    assert cleaned >= 1
    conn = sqlite3.connect(str(db))
    statuses = {
        r[0]: r[1]
        for r in conn.execute(
            "SELECT stock_code, status FROM threshold_state"
        ).fetchall()
    }
    assert statuses["300059"] == "expired"
    assert statuses["601628"] == "armed"
    conn.close()
