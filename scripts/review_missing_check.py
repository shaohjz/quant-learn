"""REQ-047: daily review presence monitor.

Workday after-close monitor for ``docs/reviews/YYYY-MM-DD.md``.
If the trading-day review is missing or empty, the script:

* appends a structured line to ``logs/review_missing.log``;
* upserts an alert into ``data/pm.db`` table ``alerts``;
* sends a best-effort WeCom webhook notification via ``sim.notifier``.

Intended scheduler: workdays 18:30 (Windows Task Scheduler / external cron).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_REVIEWS_DIR = ROOT / "docs" / "reviews"
DEFAULT_PM_DB = ROOT / "data" / "pm.db"
DEFAULT_LOG = ROOT / "logs" / "review_missing.log"


def _parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    return date.fromisoformat(value)


def _review_status(review_path: Path) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for a review markdown file."""
    if not review_path.exists():
        return False, "missing"
    if not review_path.is_file():
        return False, "not_a_file"
    try:
        content = review_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = review_path.read_text(encoding="utf-8", errors="ignore")
    if not content.strip():
        return False, "empty"
    return True, "ok"


def ensure_alerts_table(conn: sqlite3.Connection) -> None:
    """Create the PM alert table used by review monitors if it is absent."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_key TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            source TEXT NOT NULL,
            trade_date TEXT,
            metadata TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def upsert_pm_alert(
    db_path: Path,
    *,
    alert_key: str,
    title: str,
    message: str,
    trade_date: date,
    reason: str,
    review_path: Path,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata = json.dumps(
        {"reason": reason, "review_path": str(review_path)}, ensure_ascii=False
    )
    with sqlite3.connect(db_path) as conn:
        ensure_alerts_table(conn)
        conn.execute(
            """
            INSERT INTO alerts(
                alert_key, type, severity, title, message, status, source,
                trade_date, metadata, created_at, updated_at
            )
            VALUES (?, 'review_missing', 'warn', ?, ?, 'open',
                    'scripts.review_missing_check', ?, ?, ?, ?)
            ON CONFLICT(alert_key) DO UPDATE SET
                severity=excluded.severity,
                title=excluded.title,
                message=excluded.message,
                status='open',
                metadata=excluded.metadata,
                updated_at=excluded.updated_at
            """,
            (
                alert_key,
                title,
                message,
                trade_date.isoformat(),
                metadata,
                now,
                now,
            ),
        )
        conn.commit()


def append_log(log_path: Path, payload: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def build_alert_message(target_date: date, review_path: Path, reason: str) -> str:
    reason_zh = {
        "missing": "文件不存在",
        "empty": "文件为空",
        "not_a_file": "路径不是普通文件",
    }.get(reason, reason)
    try:
        rel_path = review_path.relative_to(ROOT) if review_path.is_absolute() else review_path
    except ValueError:
        rel_path = review_path
    return (
        f"⚠️ QuantLearn 工作日复盘缺失告警\n"
        f"日期：{target_date.isoformat()}\n"
        f"检查项：{rel_path}\n"
        f"问题：{reason_zh}\n"
        f"动作：已写入 pm.db alerts，并记录 logs/review_missing.log。请补齐当日复盘。"
    )


def run_check(
    target_date: date,
    *,
    reviews_dir: Path = DEFAULT_REVIEWS_DIR,
    db_path: Path = DEFAULT_PM_DB,
    log_path: Path = DEFAULT_LOG,
    push: bool = True,
    dry_run: bool = False,
    trading_day_func: Optional[Callable[[date], bool]] = None,
    notifier: Optional[Callable[[str], bool]] = None,
) -> dict:
    """Run the review monitor once and return a structured result."""
    if trading_day_func is None:
        from sim.trade_calendar import is_trading_day

        trading_day_func = is_trading_day

    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    review_path = reviews_dir / f"{target_date.isoformat()}.md"
    is_trade_day = bool(trading_day_func(target_date))

    if not is_trade_day:
        result = {
            "checked_at": checked_at,
            "date": target_date.isoformat(),
            "status": "skipped_non_trading_day",
            "review_path": str(review_path),
        }
        append_log(log_path, result)
        return result

    ok, reason = _review_status(review_path)
    if ok:
        result = {
            "checked_at": checked_at,
            "date": target_date.isoformat(),
            "status": "ok",
            "review_path": str(review_path),
        }
        append_log(log_path, result)
        return result

    title = f"工作日复盘缺失：{target_date.isoformat()}"
    message = build_alert_message(target_date, review_path, reason)
    alert_key = f"review_missing:{target_date.isoformat()}"
    result = {
        "checked_at": checked_at,
        "date": target_date.isoformat(),
        "status": "alert",
        "reason": reason,
        "alert_key": alert_key,
        "review_path": str(review_path),
        "dry_run": dry_run,
        "pushed": False,
    }

    if not dry_run:
        try:
            upsert_pm_alert(
                db_path,
                alert_key=alert_key,
                title=title,
                message=message,
                trade_date=target_date,
                reason=reason,
                review_path=review_path,
            )
        except Exception as exc:  # noqa: BLE001 - keep logging/notification visible
            result["db_error"] = str(exc)

    if push and not dry_run:
        if notifier is None:
            from sim.notifier import send_text

            notifier = send_text
        try:
            result["pushed"] = bool(notifier(message))
        except Exception as exc:  # noqa: BLE001 - monitor must not crash on notify failure
            result["push_error"] = str(exc)
            result["pushed"] = False

    append_log(log_path, {**result, "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check trading-day daily review presence")
    parser.add_argument("--date", help="target date, YYYY-MM-DD; default=today")
    parser.add_argument("--reviews-dir", default=str(DEFAULT_REVIEWS_DIR))
    parser.add_argument("--db", default=str(DEFAULT_PM_DB))
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    parser.add_argument("--no-push", action="store_true", help="do not send WeCom notification")
    parser.add_argument("--dry-run", action="store_true", help="do not write pm.db or send notification")
    args = parser.parse_args(argv)

    result = run_check(
        _parse_date(args.date),
        reviews_dir=Path(args.reviews_dir),
        db_path=Path(args.db),
        log_path=Path(args.log),
        push=not args.no_push,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
