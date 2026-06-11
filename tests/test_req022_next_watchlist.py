import sqlite3
from pathlib import Path

import yaml

from scripts import generate_next_watchlist as mod


def _make_db(path: Path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE review_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            stock_code TEXT,
            trade_date DATE,
            decision_type TEXT,
            allowed INTEGER,
            reason TEXT,
            created_at TEXT
        );
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            trade_date TEXT,
            stock_code TEXT,
            stock_name TEXT,
            direction TEXT,
            price REAL,
            quantity INTEGER,
            signal_reason TEXT,
            trade_time TEXT
        );
        CREATE TABLE sim_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            stock_code TEXT,
            stock_name TEXT,
            quantity INTEGER,
            avg_cost REAL,
            current_price REAL,
            market_value REAL,
            pnl_pct REAL
        );
        """
    )
    conn.execute(
        "INSERT INTO review_decisions (account_id, stock_code, trade_date, decision_type, allowed, reason, created_at) VALUES (1,'603693','2026-06-01','position_count_limit',0,'总持仓数超限','2026-06-01 09:40:00')"
    )
    conn.execute(
        "INSERT INTO sim_trades (account_id, trade_date, stock_code, stock_name, direction, price, quantity, signal_reason, trade_time) VALUES (1,'2026-06-01','002453','华软科技','SELL',5.92,300,'止损执行','15:34:10')"
    )
    conn.execute(
        "INSERT INTO sim_positions (account_id, stock_code, stock_name, quantity, avg_cost, current_price, market_value, pnl_pct) VALUES (1,'600186','莲花控股',1800,10.675,10.61,19098,-0.61)"
    )
    conn.commit()
    conn.close()


def test_collect_candidates_merges_review_trades_positions_and_watchlist(tmp_path, monkeypatch):
    db = tmp_path / "sim.db"
    _make_db(db)
    monkeypatch.setattr(
        mod,
        "load_watchlist_rules",
        lambda include_disabled=False: {
            "002156": {"name": "通富微电", "category": "user_manual", "added_reason": "人工关注"}
        },
    )

    candidates = mod.collect_candidates("2026-06-01", db_path=db)
    by_code = {c.code: c for c in candidates}

    assert {"603693", "002453", "600186", "002156"}.issubset(by_code)
    assert by_code["603693"].category == "blocked_buy_candidate"
    assert by_code["603693"].priority > by_code["002156"].priority
    assert "review_decisions" in by_code["603693"].source_refs
    assert "sim_trades" in by_code["002453"].source_refs
    assert "sim_positions" in by_code["600186"].source_refs


def test_update_auto_watchlist_writes_config_auto(tmp_path):
    cfg = tmp_path / "config_auto.yaml"
    candidates = [
        mod.Candidate(
            code="603693",
            name="江苏新能",
            category="blocked_buy_candidate",
            priority=82,
            reasons=["策略信号被风控拦截"],
            last_price=12.34,
        )
    ]

    added = mod.update_auto_watchlist(candidates, target_date="2026-06-02", top=10, path=cfg)
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))

    assert added == 1
    assert data["auto_discovered"]["603693"]["source"] == "next_watchlist"
    assert data["auto_discovered"]["603693"]["target_date"] == "2026-06-02"
    assert data["auto_discovered"]["603693"]["rules"]["buy_zone"]["trigger"] == 11.97
