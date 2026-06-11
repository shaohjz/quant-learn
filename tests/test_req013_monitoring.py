from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from sim.monitoring import AlertSink, HealthMonitor, format_alert, monitor_strategy_call


def _monitor(tmp_path: Path, sent: list[str] | None = None) -> tuple[HealthMonitor, Path]:
    db_path = tmp_path / "monitor.db"

    def factory():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    sink = AlertSink(sender=(sent.append if sent is not None else None), enabled=sent is not None)
    return HealthMonitor(conn_factory=factory, alert_sink=sink, alert_cooldown_seconds=60), db_path


def test_record_event_persists_and_alerts(tmp_path):
    sent: list[str] = []
    monitor, db_path = _monitor(tmp_path, sent)

    ev = monitor.record_event(
        "strategy.fusion",
        "exception",
        "error",
        "FusionStrategy on_tick 异常",
        strategy="fusion_002709",
        stock_code="002709",
        details="traceback...",
    )

    assert ev.severity == "error"
    assert len(sent) == 1
    assert "QuantLearn监控告警" in sent[0]
    assert "002709" in sent[0]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM monitoring_events").fetchone()
        status = conn.execute("SELECT * FROM component_status WHERE component='strategy.fusion'").fetchone()
    finally:
        conn.close()

    assert row["event_type"] == "exception"
    assert row["severity"] == "error"
    assert status["status"] == "error"
    assert status["last_error"] == "FusionStrategy on_tick 异常"


def test_alert_cooldown_deduplicates_delivery_but_not_storage(tmp_path):
    sent: list[str] = []
    monitor, db_path = _monitor(tmp_path, sent)

    for _ in range(2):
        monitor.record_event("qmt_broker", "connection", "critical", "QMT callback disconnected")

    assert len(sent) == 1
    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM monitoring_events").fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_check_stale_components_emits_warning(tmp_path):
    sent: list[str] = []
    monitor, db_path = _monitor(tmp_path, sent)
    monitor.heartbeat("data.eastmoney", status="ok")

    old = (datetime.now() - timedelta(seconds=600)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE component_status SET last_heartbeat=?, updated_at=? WHERE component=?",
            (old, old, "data.eastmoney"),
        )
        conn.commit()
    finally:
        conn.close()

    stale = monitor.check_stale_components(max_age_seconds=300)

    assert len(stale) == 1
    assert stale[0].event_type == "heartbeat_stale"
    assert stale[0].severity == "warn"
    assert sent and "heartbeat stale" in sent[0]


def test_data_fetch_failure_formats_source_and_stock(tmp_path):
    sent: list[str] = []
    monitor, _ = _monitor(tmp_path, sent)

    ev = monitor.record_data_fetch_failure("market_data", "eastmoney", "timeout", stock_code="600519")

    assert ev.event_type == "data_fetch_failure"
    assert ev.stock_code == "600519"
    assert "eastmoney 数据获取异常" in ev.message
    assert "600519" in format_alert(ev)


def test_strategy_decorator_records_and_reraises(tmp_path):
    sent: list[str] = []
    monitor, _ = _monitor(tmp_path, sent)

    @monitor_strategy_call(monitor, "strategy.demo", "DemoStrategy", "000001")
    def boom():
        raise RuntimeError("bad tick")

    try:
        boom()
    except RuntimeError as exc:
        assert "bad tick" in str(exc)
    else:
        raise AssertionError("decorated strategy callback should re-raise")

    events = monitor.recent_events(limit=1)
    assert events[0].component == "strategy.demo"
    assert events[0].strategy == "DemoStrategy"
    assert events[0].stock_code == "000001"
    assert events[0].event_type == "exception"
    assert sent and "DemoStrategy" in sent[0]
