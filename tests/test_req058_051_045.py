"""Tests for REQ-058, REQ-051, REQ-045."""
import sqlite3
import tempfile
import os
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _create_test_db(tmp_path):
    """Create a temp DB with the real schema and return (db_path, conn_factory)."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        'CREATE TABLE sim_account (id INTEGER PRIMARY KEY, account_name TEXT, '
        'initial_cash REAL, cash REAL, total_value REAL, '
        'created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'
    )
    conn.execute(
        "INSERT INTO sim_account VALUES (1, 'default', 100000, 100000, 100000, 'now', 'now')"
    )
    conn.execute(
        'CREATE TABLE sim_positions ('
        'id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, '
        'stock_code TEXT, stock_name TEXT, quantity INTEGER, avg_cost REAL, '
        'current_price REAL, market_value REAL, pnl REAL, pnl_pct REAL, '
        'updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, '
        'trailing_stop_price REAL, highest_price REAL)'
    )
    conn.execute(
        'CREATE TABLE sim_trades ('
        'id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER, '
        'trade_date DATE, stock_code TEXT, stock_name TEXT, direction TEXT, '
        'price REAL, quantity INTEGER, amount REAL, commission REAL, tax REAL, '
        "signal_reason TEXT, broker TEXT DEFAULT 'sim', broker_order_id TEXT, "
        'created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, signal_detail TEXT, '
        'trade_time TEXT, trade_context TEXT)'
    )
    conn.commit()
    conn.close()

    _db_str = str(db_path)

    def _make_conn():
        c = sqlite3.connect(_db_str, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        return c

    return db_path, _make_conn


@pytest.fixture
def patched_engine(tmp_path):
    """Yield (engine, db_path) with get_conn monkey-patched."""
    import sim.engine as engine_mod
    import sim.db
    db_path, conn_factory = _create_test_db(tmp_path)
    # Patch both sim.db.get_conn AND sim.engine.get_conn (imported at module level)
    orig_db = sim.db.get_conn
    orig_engine = engine_mod.get_conn
    sim.db.get_conn = conn_factory
    engine_mod.get_conn = conn_factory
    try:
        from sim.engine import SimEngine
        eng = SimEngine(account_id=1)
        yield eng, db_path
    finally:
        sim.db.get_conn = orig_db
        engine_mod.get_conn = orig_engine


# ==================== REQ-058: SELL signal_reason ====================

class TestREQ058:
    def test_build_sell_signal_reason(self):
        from sim.sell_signal_audit import build_sell_signal_reason
        r = build_sell_signal_reason('stop_loss', trigger_price=28.28, volume=400, extra='浮亏-8.5%')
        assert 'stop_loss' in r
        assert '28.28' in r
        assert '400' in r

    def test_sell_with_reason_stored(self, patched_engine):
        eng, db_path = patched_engine
        eng.buy('999101', 28.0, 100, stock_name='TEST1', signal_reason='test', trade_date=date.today())
        r = eng.sell('999101', 30.0, 100, stock_name='TEST1',
                      signal_reason='stop_loss|触发价30.000|量能100', trade_date=date.today())
        assert r['success']
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT signal_reason FROM sim_trades WHERE direction='SELL' AND stock_code='999101'")
        sr = cur.fetchone()[0]
        conn.close()
        assert sr is not None and sr != ''

    def test_sell_without_reason_auto_generates(self, patched_engine):
        eng, db_path = patched_engine
        eng.buy('999102', 28.0, 100, stock_name='TEST2', signal_reason='test', trade_date=date.today())
        r = eng.sell('999102', 30.0, 100, stock_name='TEST2',
                      signal_reason='', trade_date=date.today())
        if r['success']:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT signal_reason FROM sim_trades WHERE direction='SELL' AND stock_code='999102'")
            row = cur.fetchone()
            conn.close()
            assert row is not None, "SELL trade should exist"
            sr = row[0]
            assert sr is not None and sr != '', "Auto-generated reason should not be empty"

    def test_reconcile_sell_signals(self):
        from sim.sell_signal_audit import reconcile_sell_signals
        r = reconcile_sell_signals('2026-06-02', Path(ROOT) / 'data' / 'sim_live_mirror.db', account_id=1)
        assert hasattr(r, 'orphan_sells')
        assert hasattr(r, 'unmatched_signals')


# ==================== REQ-051: Same-stock same-day dedup ====================

class TestREQ051:
    def test_duplicate_buy_rejected(self, patched_engine):
        eng, _ = patched_engine
        r1 = eng.buy('999201', 28.0, 100, stock_name='TEST1', signal_reason='buy1', trade_date=date.today())
        assert r1['success'], f'First buy should succeed: {r1}'
        r2 = eng.buy('999201', 29.0, 100, stock_name='TEST1', signal_reason='buy2', trade_date=date.today())
        assert not r2['success'], f'Expected rejection, got {r2}'
        assert 'REQ-051' in r2['msg']

    def test_different_stock_buy_ok(self, patched_engine):
        eng, _ = patched_engine
        eng.buy('999202', 28.0, 100, stock_name='TEST2', signal_reason='buy1', trade_date=date.today())
        r = eng.buy('999203', 5.5, 100, stock_name='TEST3', signal_reason='buy2', trade_date=date.today())
        assert r['success'], f'Different stock buy should succeed: {r}'

    def test_has_buy_today(self, patched_engine):
        eng, _ = patched_engine
        assert not eng._has_buy_today('999204', str(date.today()))
        eng.buy('999204', 28.0, 100, stock_name='TEST4', signal_reason='buy1', trade_date=date.today())
        assert eng._has_buy_today('999204', str(date.today()))


# ==================== REQ-045: Cash warning ====================

class TestREQ045:
    def test_critical_level(self):
        from sim.cash_warning import check_cash_ratio
        w = check_cash_ratio(380, 22529)
        assert w.level == 'critical'
        assert not w.can_buy

    def test_low_level(self):
        from sim.cash_warning import check_cash_ratio
        w = check_cash_ratio(8000, 100000)
        assert w.level == 'low'

    def test_ok_level(self):
        from sim.cash_warning import check_cash_ratio
        w = check_cash_ratio(20000, 100000)
        assert w.level == 'ok'
        assert w.can_buy

    def test_suggest_position_critical(self):
        from sim.cash_warning import check_cash_ratio, suggest_position_size
        w = check_cash_ratio(380, 22529)
        assert suggest_position_size(500, w) == 0

    def test_suggest_position_low(self):
        from sim.cash_warning import check_cash_ratio, suggest_position_size
        w = check_cash_ratio(8000, 100000)
        s = suggest_position_size(500, w)
        assert s < 500
        assert s % 100 == 0

    def test_suggest_position_ok(self):
        from sim.cash_warning import check_cash_ratio, suggest_position_size
        w = check_cash_ratio(20000, 100000)
        assert suggest_position_size(500, w) == 500
