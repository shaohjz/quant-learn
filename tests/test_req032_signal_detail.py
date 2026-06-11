from __future__ import annotations

import importlib
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _make_old_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE sim_account (
            id INTEGER PRIMARY KEY,
            account_name TEXT,
            initial_cash REAL,
            cash REAL,
            total_value REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE sim_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER DEFAULT 1,
            stock_code TEXT,
            stock_name TEXT,
            quantity INTEGER DEFAULT 0,
            avg_cost REAL,
            current_price REAL,
            market_value REAL,
            pnl REAL,
            pnl_pct REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 模拟旧库：没有 signal_detail/trade_time/trade_context。
    cur.execute("""
        CREATE TABLE sim_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER DEFAULT 1,
            trade_date DATE,
            stock_code TEXT,
            stock_name TEXT,
            direction TEXT,
            price REAL,
            quantity INTEGER,
            amount REAL,
            commission REAL,
            tax REAL,
            signal_reason TEXT,
            broker TEXT DEFAULT 'sim',
            broker_order_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute(
        "INSERT INTO sim_account (id, account_name, initial_cash, cash, total_value) VALUES (1, 'test', 100000, 100000, 100000)"
    )
    conn.commit()
    conn.close()


def test_buy_migrates_old_trade_schema_and_persists_signal_detail(tmp_path, monkeypatch):
    db_path = tmp_path / "old_sim.db"
    _make_old_db(db_path)

    import sim.db as sim_db
    monkeypatch.setattr(sim_db, "DB_PATH", db_path)
    import sim.engine as sim_engine
    importlib.reload(sim_engine)

    detail = {
        "signal": "BUY",
        "trigger_type": "tech_buy",
        "triggered_rules": [
            {"rule": "价格进入买入区", "indicator": "price", "current_value": 9.8, "operator": "<=", "threshold": 10.0}
        ],
        "indicators_snapshot": {"RSI": 38.2, "MA5": 9.7},
        "price_snapshot": {"open": 9.6, "close": 9.8, "volume": 123456},
        "strategy_version": "unit-test/v1",
        "timestamp": "2026-06-01T09:00:00",
    }

    engine = sim_engine.SimEngine(account_id=1)
    result = engine.buy("000001", 9.8, 100, "平安银行", "buy_zone 摘要", date(2026, 6, 1), signal_detail=detail)
    assert result["success"], result

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(sim_trades)")}
    assert "signal_detail" in cols
    assert "trade_time" in cols
    assert "trade_context" in cols
    row = conn.execute("SELECT signal_reason, signal_detail FROM sim_trades WHERE stock_code='000001'").fetchone()
    conn.close()

    assert row["signal_reason"] == "buy_zone 摘要"
    saved = json.loads(row["signal_detail"])
    assert saved["strategy_version"] == "unit-test/v1"
    assert saved["triggered_rules"][0]["threshold"] == 10.0
    assert saved["indicators_snapshot"]["RSI"] == 38.2


def test_daily_review_renders_expandable_signal_detail():
    from scripts.daily_review import render_signal_detail_lines

    detail = {
        "trigger_type": "tech_buy",
        "triggered_rules": [
            {"rule": "RSI 回升", "indicator": "RSI", "current_value": 41.2, "operator": ">=", "threshold": 40}
        ],
        "indicators_snapshot": {"RSI": 41.2, "MACD": 0.1234},
        "price_snapshot": {"close": 12.34, "volume": 100000},
        "strategy_version": "signal_generator.py/v1.0",
        "timestamp": "2026-06-01T09:00:00",
    }

    lines = render_signal_detail_lines(json.dumps(detail, ensure_ascii=False))
    text = "\n".join(lines)
    assert "<details>" in text
    assert "查看完整信号解释" in text
    assert "RSI 回升" in text
    assert "指标快照" in text
    assert "行情快照" in text
