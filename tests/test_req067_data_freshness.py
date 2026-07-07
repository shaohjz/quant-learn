"""
tests/test_req067_data_freshness.py — 数据新鲜度监控测试 (REQ-067)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.data_freshness_monitor import (
    _parse_timestamp,
    _hours_ago,
    check_sim_positions,
    check_sim_daily_nav,
    check_strategy_shadow_signals,
    check_watchlist_history,
    run_all_checks,
    ensure_alerts_table,
    save_alerts_to_pm,
    format_report,
    check_freshness_for_daily,
    DATA_SOURCE_THRESHOLDS,
)


# ── helpers ────────────────────────────────────────────────────────

def _make_test_db(path: Path) -> None:
    """创建包含所有相关表的测试数据库。"""
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()

    # sim_positions
    cur.execute("""
        CREATE TABLE sim_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            stock_code TEXT,
            stock_name TEXT,
            quantity INTEGER,
            avg_cost REAL,
            current_price REAL,
            market_value REAL,
            pnl REAL,
            pnl_pct REAL,
            updated_at TIMESTAMP,
            trailing_stop_price REAL,
            highest_price REAL
        )
    """)

    # sim_daily_nav
    cur.execute("""
        CREATE TABLE sim_daily_nav (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER,
            trade_date DATE,
            total_value REAL,
            cash REAL,
            market_value REAL,
            daily_return REAL,
            cumulative_return REAL,
            max_drawdown REAL,
            created_at TIMESTAMP,
            cash_jump_detected INTEGER,
            cash_jump_reason TEXT
        )
    """)

    # strategy_shadow_signals
    cur.execute("""
        CREATE TABLE strategy_shadow_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shadow_date TEXT,
            shadow_time TEXT,
            strategy_id TEXT,
            stock_code TEXT,
            stock_name TEXT,
            price REAL,
            position INTEGER,
            signal_action TEXT,
            signal_rule TEXT,
            signal_reason TEXT,
            confidence REAL,
            created_at DATETIME
        )
    """)

    # watchlist_history
    cur.execute("""
        CREATE TABLE watchlist_history (
            code TEXT,
            name TEXT,
            category TEXT,
            added_at TEXT,
            added_by TEXT,
            added_reason TEXT,
            discovery_score REAL,
            metadata TEXT,
            last_alert_at TEXT,
            alert_count INTEGER
        )
    """)

    conn.commit()
    conn.close()


# ── unit tests ─────────────────────────────────────────────────────

class TestParseTimestamp:
    def test_parse_dt_format(self):
        dt = _parse_timestamp("2026-07-06 12:00:00")
        assert dt == datetime(2026, 7, 6, 12, 0, 0)

    def test_parse_iso_format(self):
        dt = _parse_timestamp("2026-07-06T12:00:00")
        assert dt == datetime(2026, 7, 6, 12, 0, 0)

    def test_parse_date_only(self):
        dt = _parse_timestamp("2026-07-06")
        assert dt == datetime(2026, 7, 6, 0, 0, 0)

    def test_parse_none(self):
        assert _parse_timestamp(None) is None

    def test_parse_invalid(self):
        assert _parse_timestamp("not-a-date") is None


class TestHoursAgo:
    def test_basic(self):
        now = datetime(2026, 7, 6, 12, 0, 0)
        dt = datetime(2026, 7, 6, 8, 0, 0)
        assert _hours_ago(dt, now) == 4.0

    def test_none(self):
        assert _hours_ago(None) is None


# ── integration tests ──────────────────────────────────────────────

class TestCheckSimPositions:
    def test_fresh(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            ts = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            conn = sqlite3.connect(str(path))
            conn.execute(
                "INSERT INTO sim_positions(account_id, stock_code, quantity, avg_cost, current_price, updated_at) "
                "VALUES (1, '000001', 100, 10.0, 11.0, ?)", (ts,)
            )
            conn.commit()
            conn.close()

            result = check_sim_positions(path, 24, now)
            assert result["ok"] is True
            assert "新鲜" in result["message"]
            assert result["age_hours"] == 1.0
        finally:
            path.unlink(missing_ok=True)

    def test_stale(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            ts = (now - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
            conn = sqlite3.connect(str(path))
            conn.execute(
                "INSERT INTO sim_positions(account_id, stock_code, quantity, avg_cost, current_price, updated_at) "
                "VALUES (1, '000001', 100, 10.0, 11.0, ?)", (ts,)
            )
            conn.commit()
            conn.close()

            result = check_sim_positions(path, 24, now)
            assert result["ok"] is False
            assert "过时" in result["message"] or "stale" in result["message"].lower()
            assert result["age_hours"] == 48.0
        finally:
            path.unlink(missing_ok=True)

    def test_empty_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            result = check_sim_positions(path, 24, now)
            assert result["ok"] is True
            assert "无数据" in result["message"]
        finally:
            path.unlink(missing_ok=True)

    def test_db_not_found(self):
        path = Path("/nonexistent/path.db")
        result = check_sim_positions(path, 24)
        assert result["ok"] is False
        assert "不存在" in result["message"]


class TestCheckSimDailyNav:
    def test_fresh_today(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            conn = sqlite3.connect(str(path))
            conn.execute(
                "INSERT INTO sim_daily_nav(account_id, trade_date, total_value, cash, market_value) "
                "VALUES (1, '2026-07-06', 100000, 50000, 50000)"
            )
            conn.commit()
            conn.close()

            result = check_sim_daily_nav(path, 24, now)
            assert result["ok"] is True
            assert "已覆盖到今天" in result["message"]
            assert result["age_hours"] == 0
        finally:
            path.unlink(missing_ok=True)

    def test_stale_3_days(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            conn = sqlite3.connect(str(path))
            conn.execute(
                "INSERT INTO sim_daily_nav(account_id, trade_date, total_value, cash, market_value) "
                "VALUES (1, '2026-07-01', 100000, 50000, 50000)"
            )
            conn.commit()
            conn.close()

            result = check_sim_daily_nav(path, 24, now)
            assert result["ok"] is False
            assert result["age_hours"] == 5 * 24  # 5 days behind
            assert "过时" in result["message"]
        finally:
            path.unlink(missing_ok=True)

    def test_stale_1_day_within_threshold(self):
        """1天前的数据在48h阈值内不算异常"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            conn = sqlite3.connect(str(path))
            conn.execute(
                "INSERT INTO sim_daily_nav(account_id, trade_date, total_value, cash, market_value) "
                "VALUES (1, '2026-07-05', 100000, 50000, 50000)"
            )
            conn.commit()
            conn.close()

            result = check_sim_daily_nav(path, 48, now)  # 阈值48h
            assert result["ok"] is True
        finally:
            path.unlink(missing_ok=True)


class TestCheckStrategyShadowSignals:
    def test_fresh_today(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            conn = sqlite3.connect(str(path))
            conn.execute(
                "INSERT INTO strategy_shadow_signals(shadow_date, shadow_time, strategy_id, stock_code, stock_name, price, position, signal_action, signal_rule, signal_reason, confidence) "
                "VALUES ('2026-07-06', '10:00:00', 'macd', '000001', 'Test', 10.0, 100, 'BUY', 'golden_cross', 'test', 0.8)"
            )
            conn.commit()
            conn.close()

            result = check_strategy_shadow_signals(path, 24, now)
            assert result["ok"] is True
            assert result["today_signal_count"] == 1
            assert "已覆盖到今天" in result["message"]
        finally:
            path.unlink(missing_ok=True)

    def test_stale_2_days(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            conn = sqlite3.connect(str(path))
            conn.execute(
                "INSERT INTO strategy_shadow_signals(shadow_date, shadow_time, strategy_id, stock_code, stock_name, price, position, signal_action, signal_rule, signal_reason, confidence) "
                "VALUES ('2026-07-04', '10:00:00', 'macd', '000001', 'Test', 10.0, 100, 'BUY', 'golden_cross', 'test', 0.8)"
            )
            conn.commit()
            conn.close()

            result = check_strategy_shadow_signals(path, 24, now)
            assert result["ok"] is False
        finally:
            path.unlink(missing_ok=True)

    def test_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            result = check_strategy_shadow_signals(path, 24, now)
            assert result["ok"] is True
            assert "无数据" in result["message"]
        finally:
            path.unlink(missing_ok=True)


class TestCheckWatchlistHistory:
    def test_with_alerts(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            alert_ts = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
            conn = sqlite3.connect(str(path))
            conn.execute(
                "INSERT INTO watchlist_history(code, name, category, added_at, last_alert_at, alert_count) "
                "VALUES ('000001', 'Test', 'auto', '2026-07-01', ?, 3)", (alert_ts,)
            )
            conn.commit()
            conn.close()

            result = check_watchlist_history(path, 24, now)
            assert result["ok"] is True  # never blocks
            assert result["total_items"] == 1
            assert "新鲜" in result["message"]
        finally:
            path.unlink(missing_ok=True)

    def test_no_alerts(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            conn = sqlite3.connect(str(path))
            conn.execute(
                "INSERT INTO watchlist_history(code, name, category, added_at) "
                "VALUES ('000001', 'Test', 'auto', '2026-07-01')"
            )
            conn.commit()
            conn.close()

            result = check_watchlist_history(path, 24, now)
            assert result["ok"] is True
            assert "无告警" in result["message"]
        finally:
            path.unlink(missing_ok=True)


# ── integration: run_all_checks ────────────────────────────────────

class TestRunAllChecks:
    def test_all_fresh(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            conn = sqlite3.connect(str(path))
            ts = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO sim_positions(account_id, stock_code, quantity, avg_cost, current_price, updated_at) "
                "VALUES (1, '000001', 100, 10.0, 11.0, ?)", (ts,)
            )
            conn.execute(
                "INSERT INTO sim_daily_nav(account_id, trade_date, total_value, cash, market_value) "
                "VALUES (1, '2026-07-06', 100000, 50000, 50000)"
            )
            conn.execute(
                "INSERT INTO strategy_shadow_signals(shadow_date, shadow_time, strategy_id, stock_code, stock_name, price, position, signal_action, signal_rule, signal_reason, confidence) "
                "VALUES ('2026-07-06', '10:00:00', 'macd', '000001', 'Test', 10.0, 100, 'BUY', 'golden_cross', 'test', 0.8)"
            )
            conn.commit()
            conn.close()

            thresholds = dict.fromkeys(DATA_SOURCE_THRESHOLDS.keys(), 24)
            results = run_all_checks(path, thresholds, now)
            assert len(results) == 4
            # 前三个数据源应该都通过
            for r in results[:3]:
                assert r["ok"] is True, f"{r['source']}: {r['message']}"
        finally:
            path.unlink(missing_ok=True)

    def test_some_stale(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            conn = sqlite3.connect(str(path))
            stale = (now - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO sim_positions(account_id, stock_code, quantity, avg_cost, current_price, updated_at) "
                "VALUES (1, '000001', 100, 10.0, 11.0, ?)", (stale,)
            )
            conn.execute(
                "INSERT INTO sim_daily_nav(account_id, trade_date, total_value, cash, market_value) "
                "VALUES (1, '2026-06-01', 100000, 50000, 50000)"
            )
            conn.execute(
                "INSERT INTO strategy_shadow_signals(shadow_date, shadow_time, strategy_id, stock_code, stock_name, price, position, signal_action, signal_rule, signal_reason, confidence) "
                "VALUES ('2026-06-01', '10:00:00', 'macd', '000001', 'Test', 10.0, 100, 'BUY', 'golden_cross', 'test', 0.8)"
            )
            conn.commit()
            conn.close()

            thresholds = dict.fromkeys(DATA_SOURCE_THRESHOLDS.keys(), 24)
            results = run_all_checks(path, thresholds, now)
            failed = [r for r in results if not r["ok"]]
            # sim_positions, sim_daily_nav, strategy_shadow_signals 都应该失败
            assert len(failed) >= 3, f"Expected >=3 failures, got {len(failed)}: {failed}"
        finally:
            path.unlink(missing_ok=True)


# ── PM alerts table ────────────────────────────────────────────────

class TestPMAlerts:
    def test_ensure_alerts_table(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            pm_path = Path(f.name)
        try:
            ensure_alerts_table(pm_path)
            conn = sqlite3.connect(str(pm_path))
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='freshness_alerts'"
            )
            assert cur.fetchone() is not None
            conn.close()
        finally:
            pm_path.unlink(missing_ok=True)

    def test_save_and_retrieve_alerts(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            pm_path = Path(f.name)
        try:
            results = [
                {"source": "sim_positions", "ok": True, "age_hours": 1.0,
                 "latest_ts": "2026-07-06 11:00:00", "threshold_hours": 24,
                 "message": "ok"},
                {"source": "sim_daily_nav", "ok": False, "age_hours": 72.0,
                 "latest_ts": "2026-07-03", "threshold_hours": 24,
                 "message": "stale"},
            ]
            count = save_alerts_to_pm(pm_path, results, "2026-07-06 12:00:00")
            assert count == 2

            conn = sqlite3.connect(str(pm_path))
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM freshness_alerts")
            assert cur.fetchone()[0] == 2

            cur.execute("SELECT source, ok FROM freshness_alerts ORDER BY id")
            rows = cur.fetchall()
            assert rows[0] == ("sim_positions", 1)
            assert rows[1] == ("sim_daily_nav", 0)
            conn.close()
        finally:
            pm_path.unlink(missing_ok=True)


# ── format_report ──────────────────────────────────────────────────

class TestFormatReport:
    def test_format(self):
        results = [
            {"source": "sim_positions", "ok": True,
             "message": "[sim_positions] OK"},
            {"source": "sim_daily_nav", "ok": False,
             "message": "[sim_daily_nav] FAIL"},
        ]
        report = format_report(results, "2026-07-06 12:00:00")
        assert "数据新鲜度监控报告" in report
        assert "2026-07-06 12:00:00" in report
        assert "1 正常" in report
        assert "1 异常" in report
        assert "OK" in report
        assert "FAIL" in report


# ── check_freshness_for_daily integration ──────────────────────────

class TestDailyCheckIntegration:
    def test_all_fresh(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            conn = sqlite3.connect(str(path))
            ts = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO sim_positions(account_id, stock_code, quantity, avg_cost, current_price, updated_at) "
                "VALUES (1, '000001', 100, 10.0, 11.0, ?)", (ts,)
            )
            conn.execute(
                "INSERT INTO sim_daily_nav(account_id, trade_date, total_value, cash, market_value) "
                "VALUES (1, '2026-07-06', 100000, 50000, 50000)"
            )
            conn.execute(
                "INSERT INTO strategy_shadow_signals(shadow_date, shadow_time, strategy_id, stock_code, stock_name, price, position, signal_action, signal_rule, signal_reason, confidence) "
                "VALUES ('2026-07-06', '10:00:00', 'macd', '000001', 'Test', 10.0, 100, 'BUY', 'golden_cross', 'test', 0.8)"
            )
            conn.commit()
            conn.close()

            thresholds = dict.fromkeys(DATA_SOURCE_THRESHOLDS.keys(), 24)
            # Override now for testing by calling run_all_checks directly
            # check_freshness_for_daily doesn't accept now, so we patch via thresholds
            import scripts.data_freshness_monitor as mod
            real_run = mod.run_all_checks
            mod.run_all_checks = lambda db, thr: real_run(db, thr, now)
            try:
                ok, summary, results = check_freshness_for_daily(path, thresholds)
                assert ok is True
                assert "4/4" in summary  # 4 checks total
            finally:
                mod.run_all_checks = real_run
        finally:
            path.unlink(missing_ok=True)

    def test_some_stale(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        try:
            _make_test_db(path)
            now = datetime(2026, 7, 6, 12, 0, 0)
            conn = sqlite3.connect(str(path))
            stale = (now - timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO sim_positions(account_id, stock_code, quantity, avg_cost, current_price, updated_at) "
                "VALUES (1, '000001', 100, 10.0, 11.0, ?)", (stale,)
            )
            conn.execute(
                "INSERT INTO sim_daily_nav(account_id, trade_date, total_value, cash, market_value) "
                "VALUES (1, '2026-07-06', 100000, 50000, 50000)"
            )
            conn.commit()
            conn.close()

            thresholds = dict.fromkeys(DATA_SOURCE_THRESHOLDS.keys(), 24)
            ok, summary, results = check_freshness_for_daily(path, thresholds)
            assert ok is False
            assert "异常" in summary
        finally:
            path.unlink(missing_ok=True)
