"""System and strategy monitoring helpers for QuantLearn.

REQ-013 adds a lightweight, dependency-free monitoring layer that can be used
from brokers, runners and strategies without coupling them to a specific alert
transport.  The module records:

* component heartbeats / connection state
* strategy-level exceptions
* data fetch failures and stale component checks

Events are persisted to SQLite for post-mortem review and severe events are
forwarded through a pluggable alert sink (defaults to ``notifier.push_text``).
Alert delivery is best-effort: monitoring must never crash trading code.
"""
from __future__ import annotations

import logging
import sqlite3
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from sim.db import get_conn

logger = logging.getLogger(__name__)

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_ERROR = "error"
SEVERITY_CRITICAL = "critical"
_ALERTING_SEVERITIES = {SEVERITY_WARN, SEVERITY_ERROR, SEVERITY_CRITICAL}


@dataclass(frozen=True)
class MonitorEvent:
    """A normalized monitoring event."""

    component: str
    event_type: str
    severity: str
    message: str
    strategy: str = ""
    stock_code: str = ""
    details: str = ""
    created_at: str = ""


class AlertSink:
    """Best-effort alert sink used by ``HealthMonitor``.

    ``sender`` is expected to accept a single text argument and return a truthy
    value on success.  By default we use ``notifier.push_text`` lazily so tests
    and offline scripts can inject a fake sender without importing notifier.
    """

    def __init__(self, sender: Optional[Callable[[str], Any]] = None, enabled: bool = True):
        self.sender = sender
        self.enabled = enabled

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            sender = self.sender
            if sender is None:
                from notifier import push_text  # imported lazily; may dry-run by config

                sender = push_text
            return bool(sender(text))
        except Exception:  # noqa: BLE001 - monitoring must not raise into strategy loop
            logger.exception("monitor alert delivery failed")
            return False


class HealthMonitor:
    """Persist runtime health signals and emit deduplicated alerts.

    Parameters
    ----------
    conn_factory:
        Optional SQLite connection factory.  Defaults to ``sim.db.get_conn``.
        Tests can inject a temporary in-memory/on-disk database.
    alert_sink:
        Optional alert sink.  Pass ``AlertSink(enabled=False)`` to disable
        delivery while still recording events.
    alert_cooldown_seconds:
        Minimum interval for sending the same alert key.  Events are always
        stored; only repeated notification delivery is suppressed.
    """

    def __init__(
        self,
        conn_factory: Callable[[], sqlite3.Connection] = get_conn,
        alert_sink: Optional[AlertSink] = None,
        alert_cooldown_seconds: int = 300,
    ):
        self.conn_factory = conn_factory
        self.alert_sink = alert_sink if alert_sink is not None else AlertSink()
        self.alert_cooldown = timedelta(seconds=alert_cooldown_seconds)
        self._last_alert_at: dict[tuple[str, str, str, str], datetime] = {}

    def ensure_tables(self) -> None:
        conn = self.conn_factory()
        try:
            _ensure_tables(conn)
        finally:
            conn.close()

    def heartbeat(self, component: str, status: str = "ok", details: str = "") -> None:
        """Record a component heartbeat/status snapshot."""
        now = _now()
        conn = self.conn_factory()
        try:
            _ensure_tables(conn)
            conn.execute(
                """
                INSERT INTO component_status(component, status, last_heartbeat, details, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(component) DO UPDATE SET
                    status=excluded.status,
                    last_heartbeat=excluded.last_heartbeat,
                    details=excluded.details,
                    updated_at=excluded.updated_at
                """,
                (component, status, now, details, now),
            )
            conn.commit()
        finally:
            conn.close()

    def record_event(
        self,
        component: str,
        event_type: str,
        severity: str,
        message: str,
        *,
        strategy: str = "",
        stock_code: str = "",
        details: str = "",
        alert: Optional[bool] = None,
    ) -> MonitorEvent:
        """Persist an event and optionally notify the alert sink."""
        severity = _normalize_severity(severity)
        event = MonitorEvent(
            component=component,
            event_type=event_type,
            severity=severity,
            message=message,
            strategy=strategy or "",
            stock_code=stock_code or "",
            details=details or "",
            created_at=_now(),
        )
        conn = self.conn_factory()
        try:
            _ensure_tables(conn)
            conn.execute(
                """
                INSERT INTO monitoring_events(
                    component, strategy, stock_code, event_type, severity, message, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.component,
                    event.strategy,
                    event.stock_code,
                    event.event_type,
                    event.severity,
                    event.message,
                    event.details,
                    event.created_at,
                ),
            )
            if severity in {SEVERITY_ERROR, SEVERITY_CRITICAL}:
                conn.execute(
                    """
                    INSERT INTO component_status(component, status, last_error, details, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(component) DO UPDATE SET
                        status=excluded.status,
                        last_error=excluded.last_error,
                        details=excluded.details,
                        updated_at=excluded.updated_at
                    """,
                    (component, severity, event.message, event.details, event.created_at),
                )
            conn.commit()
        finally:
            conn.close()

        should_alert = severity in _ALERTING_SEVERITIES if alert is None else bool(alert)
        if should_alert:
            self._send_alert(event)
        return event

    def record_exception(
        self,
        component: str,
        exc: BaseException,
        *,
        strategy: str = "",
        stock_code: str = "",
        message: str = "",
        severity: str = SEVERITY_ERROR,
    ) -> MonitorEvent:
        """Persist an exception with traceback and emit an alert."""
        summary = message or f"{type(exc).__name__}: {exc}"
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return self.record_event(
            component,
            "exception",
            severity,
            summary,
            strategy=strategy,
            stock_code=stock_code,
            details=details,
            alert=True,
        )

    def record_connection_state(self, component: str, connected: bool, message: str = "") -> MonitorEvent:
        """Record connection up/down state; disconnected states alert."""
        status = "connected" if connected else "disconnected"
        self.heartbeat(component, status=status, details=message)
        return self.record_event(
            component,
            "connection",
            SEVERITY_INFO if connected else SEVERITY_CRITICAL,
            message or status,
            alert=not connected,
        )

    def record_data_fetch_failure(
        self,
        component: str,
        source: str,
        exc_or_message: BaseException | str,
        *,
        stock_code: str = "",
        severity: str = SEVERITY_WARN,
    ) -> MonitorEvent:
        """Record a data-source failure without crashing caller code."""
        if isinstance(exc_or_message, BaseException):
            message = f"{source} 数据获取异常: {type(exc_or_message).__name__}: {exc_or_message}"
            details = "".join(
                traceback.format_exception(type(exc_or_message), exc_or_message, exc_or_message.__traceback__)
            )
        else:
            message = f"{source} 数据获取异常: {exc_or_message}"
            details = ""
        return self.record_event(
            component,
            "data_fetch_failure",
            severity,
            message,
            stock_code=stock_code,
            details=details,
            alert=True,
        )

    def check_stale_components(self, max_age_seconds: int = 300) -> list[MonitorEvent]:
        """Alert on components whose latest heartbeat is older than max_age."""
        cutoff = datetime.now() - timedelta(seconds=max_age_seconds)
        events: list[MonitorEvent] = []
        conn = self.conn_factory()
        try:
            _ensure_tables(conn)
            rows = conn.execute(
                "SELECT component, status, last_heartbeat FROM component_status WHERE last_heartbeat IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            last = _parse_dt(row["last_heartbeat"] if isinstance(row, sqlite3.Row) else row[2])
            component = row["component"] if isinstance(row, sqlite3.Row) else row[0]
            status = row["status"] if isinstance(row, sqlite3.Row) else row[1]
            if last and last < cutoff:
                age = int((datetime.now() - last).total_seconds())
                events.append(
                    self.record_event(
                        component,
                        "heartbeat_stale",
                        SEVERITY_WARN,
                        f"{component} heartbeat stale: {age}s since last status={status}",
                        alert=True,
                    )
                )
        return events

    def recent_events(self, limit: int = 20, min_severity: str | None = None) -> list[MonitorEvent]:
        """Return recent events for diagnostics/tests."""
        params: list[Any] = []
        sql = (
            "SELECT component, strategy, stock_code, event_type, severity, message, details, created_at "
            "FROM monitoring_events"
        )
        if min_severity:
            allowed = _severity_at_least(min_severity)
            placeholders = ",".join("?" for _ in allowed)
            sql += f" WHERE severity IN ({placeholders})"
            params.extend(allowed)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        conn = self.conn_factory()
        try:
            _ensure_tables(conn)
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [
            MonitorEvent(
                component=r["component"],
                strategy=r["strategy"] or "",
                stock_code=r["stock_code"] or "",
                event_type=r["event_type"],
                severity=r["severity"],
                message=r["message"],
                details=r["details"] or "",
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def _send_alert(self, event: MonitorEvent) -> bool:
        key = (event.component, event.strategy, event.event_type, event.message)
        now = datetime.now()
        last = self._last_alert_at.get(key)
        if last and now - last < self.alert_cooldown:
            return False
        self._last_alert_at[key] = now
        return self.alert_sink.send(format_alert(event))


def monitor_strategy_call(
    monitor: HealthMonitor,
    component: str,
    strategy: str,
    stock_code: str = "",
):
    """Decorator factory to record strategy callback exceptions.

    Example:
        @monitor_strategy_call(monitor, "fusion", "FusionStrategy", "002709")
        def on_tick(...): ...
    """

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                monitor.record_exception(component, exc, strategy=strategy, stock_code=stock_code)
                raise

        return _wrapped

    return _decorator


def format_alert(event: MonitorEvent) -> str:
    """Format an event as a compact WeCom-friendly alert."""
    icon = "🚨" if event.severity in {SEVERITY_ERROR, SEVERITY_CRITICAL} else "⚠️"
    bits = [f"{icon} QuantLearn监控告警", f"级别: {event.severity}", f"组件: {event.component}"]
    if event.strategy:
        bits.append(f"策略: {event.strategy}")
    if event.stock_code:
        bits.append(f"标的: {event.stock_code}")
    bits.extend([f"类型: {event.event_type}", f"信息: {event.message}", f"时间: {event.created_at or _now()}"])
    if event.details:
        clipped = event.details.strip().replace("\r", "")[-800:]
        bits.append(f"详情: {clipped}")
    return "\n".join(bits)


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS monitoring_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component TEXT NOT NULL,
            strategy TEXT DEFAULT '',
            stock_code TEXT DEFAULT '',
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS component_status (
            component TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            last_heartbeat TEXT,
            last_error TEXT,
            details TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_events_created ON monitoring_events(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_monitoring_events_component ON monitoring_events(component, severity)")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def _normalize_severity(severity: str) -> str:
    sev = (severity or SEVERITY_INFO).lower()
    return sev if sev in {SEVERITY_INFO, SEVERITY_WARN, SEVERITY_ERROR, SEVERITY_CRITICAL} else SEVERITY_INFO


def _severity_at_least(min_severity: str) -> Iterable[str]:
    order = [SEVERITY_INFO, SEVERITY_WARN, SEVERITY_ERROR, SEVERITY_CRITICAL]
    min_severity = _normalize_severity(min_severity)
    return order[order.index(min_severity) :]


_default_monitor: HealthMonitor | None = None


def get_default_monitor() -> HealthMonitor:
    """Return process-wide monitor singleton."""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = HealthMonitor()
    return _default_monitor


# ============================================================
# REQ-045: 现金占比过低预警
# ============================================================

# 默认阈值：现金占比低于此值触发告警
DEFAULT_CASH_RATIO_WARN = 0.05   # 5% 警告
DEFAULT_CASH_RATIO_CRIT = 0.02   # 2% 严重


def check_cash_ratio(
    account_id: int = 1,
    warn_threshold: float | None = None,
    crit_threshold: float | None = None,
    monitor: HealthMonitor | None = None,
) -> dict:
    """REQ-045: 检查现金占比，低于阈值时产生告警。

    现金占比 = cash / total_value
    - 低于 warn_threshold (默认 5%) → warn 告警
    - 低于 crit_threshold (默认 2%) → critical 告警

    Args:
        account_id: 账户 ID
        warn_threshold: 警告阈值（0-1），默认从 config 读取或 0.05
        crit_threshold: 严重阈值（0-1），默认从 config 读取或 0.02
        monitor: HealthMonitor 实例，默认用 get_default_monitor()

    Returns:
        {
            "cash_ratio": float,      # 0-1
            "cash": float,
            "total_value": float,
            "level": "ok"|"warn"|"critical",
            "message": str,
            "alert_sent": bool,
        }
    """
    from sim.config import get as config_get

    # 读取阈值
    if warn_threshold is None:
        warn_threshold = float(config_get("risk.cash_ratio_warn", DEFAULT_CASH_RATIO_WARN))
    if crit_threshold is None:
        crit_threshold = float(config_get("risk.cash_ratio_crit", DEFAULT_CASH_RATIO_CRIT))

    # 读取账户数据
    from sim.db import get_conn
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT cash, total_value, initial_cash FROM sim_account WHERE id = ?",
            (account_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return {
            "cash_ratio": 0, "cash": 0, "total_value": 0,
            "level": "critical", "message": f"账户 {account_id} 不存在",
            "alert_sent": False,
        }

    cash = float(row["cash"])
    total_value = float(row["total_value"])
    if total_value <= 0:
        return {
            "cash_ratio": 0, "cash": cash, "total_value": total_value,
            "level": "critical", "message": f"总资产异常（{total_value}）",
            "alert_sent": False,
        }

    cash_ratio = cash / total_value

    # 判定级别
    if cash_ratio < crit_threshold:
        level = "critical"
        message = (
            f"🚨 现金占比仅 {cash_ratio*100:.1f}%（¥{cash:,.0f}/¥{total_value:,.0f}），"
            f"低于严重阈值 {crit_threshold*100:.0f}%，"
            f"建议卖出部分浮亏仓位释放流动性"
        )
    elif cash_ratio < warn_threshold:
        level = "warn"
        message = (
            f"⚠️ 现金占比 {cash_ratio*100:.1f}%（¥{cash:,.0f}/¥{total_value:,.0f}），"
            f"低于警告阈值 {warn_threshold*100:.0f}%，"
            f"建议控制买入节奏"
        )
    else:
        level = "ok"
        message = f"✅ 现金占比 {cash_ratio*100:.1f}%（¥{cash:,.0f}/¥{total_value:,.0f}），正常"

    # 发送告警
    alert_sent = False
    if level in ("warn", "critical"):
        _monitor = monitor or get_default_monitor()
        severity = SEVERITY_CRITICAL if level == "critical" else SEVERITY_WARN
        event = _monitor.record_event(
            component="cash_ratio",
            event_type="low_cash_ratio",
            severity=severity,
            message=message,
            details=f"cash={cash}, total_value={total_value}, cash_ratio={cash_ratio:.4f}, "
                    f"warn_threshold={warn_threshold}, crit_threshold={crit_threshold}",
            alert=True,
        )
        alert_sent = True

    return {
        "cash_ratio": round(cash_ratio, 4),
        "cash": round(cash, 2),
        "total_value": round(total_value, 2),
        "level": level,
        "message": message,
        "alert_sent": alert_sent,
    }
