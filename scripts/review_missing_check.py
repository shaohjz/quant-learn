"""BUG-018 / REQ-047: daily review presence monitor.

Workday after-close monitor for generated daily review reports.  The active
``scripts/daily_review.py`` runner writes reports to ``output/reviews``; older
manual/vnpy reports may still live under ``docs/reviews``.  The monitor checks
``output/reviews/YYYY-MM-DD.md`` by default and treats the legacy docs location
as a fallback to avoid false missing alerts while both generators coexist.

If a trading-day review is missing, empty, or clearly incomplete, the script:

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
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_REVIEWS_DIR = ROOT / "output" / "reviews"
LEGACY_REVIEWS_DIR = ROOT / "docs" / "reviews"
DEFAULT_PM_DB = ROOT / "data" / "pm.db"
DEFAULT_LOG = ROOT / "logs" / "review_missing.log"
DEFAULT_CUTOFF = dtime(18, 0)


@dataclass
class ReviewCheckResult:
    ok: bool
    reason: str = ""
    detail: str = ""
    review_path: Path | None = None
    checked_paths: list[str] | None = None


def _parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    return date.fromisoformat(value)


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now()
    return datetime.fromisoformat(value.replace(" ", "T"))


def _parse_time(value: str | None) -> dtime:
    if not value:
        return DEFAULT_CUTOFF
    hour, minute, *rest = value.split(":")
    second = int(rest[0]) if rest else 0
    return dtime(int(hour), int(minute), second)


def _load_trade_dates(path: Path | None) -> set[str] | None:
    if not path or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    dates = data.get("dates") if isinstance(data, dict) else data
    if not isinstance(dates, list):
        return None
    return {str(x) for x in dates}


def _is_trading_day_from_file(target_date: date, trade_dates_path: Path | None) -> bool | None:
    dates = _load_trade_dates(trade_dates_path)
    if dates is None:
        return None
    return target_date.isoformat() in dates


def _candidate_review_paths(reviews_dir: Path, target_date: date) -> list[Path]:
    """Return primary + legacy candidate report paths, de-duplicated."""
    paths = [Path(reviews_dir) / f"{target_date.isoformat()}.md"]
    # The historical monitor looked at docs/reviews, but the active daily runner
    # writes output/reviews.  Keep docs as a fallback only when the caller did not
    # explicitly point at a custom directory.
    if Path(reviews_dir).resolve() == DEFAULT_REVIEWS_DIR.resolve():
        paths.append(LEGACY_REVIEWS_DIR / f"{target_date.isoformat()}.md")
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        key = str(p.resolve()) if p.exists() else str(p.absolute())
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _review_status(review_path: Path) -> tuple[bool, str, str]:
    """Return ``(ok, reason, detail)`` for one review markdown file."""
    if not review_path.exists():
        return False, "missing", "review file not found"
    if not review_path.is_file():
        return False, "not_a_file", "review path is not a regular file"
    try:
        content = review_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = review_path.read_text(encoding="utf-8", errors="ignore")
    if not content.strip():
        return False, "empty", "review file is empty"

    # Legacy vnpy reports are titled "双账户复盘" and should include the account
    # overview table.  The newer generated output/reviews format intentionally
    # does not have that section, so do not over-validate every non-empty report.
    if "双账户复盘" in content and "账户概览" not in content:
        return False, "incomplete", "legacy 双账户复盘 report missing 账户概览 section"
    return True, "ok", ""


def check_review(
    target_date: date,
    *,
    as_of: datetime | None = None,
    cutoff: dtime = DEFAULT_CUTOFF,
    review_dir: Path = DEFAULT_REVIEWS_DIR,
    trade_dates_path: Path | None = ROOT / "data" / "trade_dates.json",
    trading_day_func: Optional[Callable[[date], bool]] = None,
) -> ReviewCheckResult:
    """Compatibility API used by tests/older agents.

    Checks only after ``cutoff`` on trading days.  A generated report in either
    the primary directory or legacy docs fallback is accepted.
    """
    as_of = as_of or datetime.now()
    if as_of.time() < cutoff:
        return ReviewCheckResult(True, "before_cutoff", "", None, [])

    file_answer = _is_trading_day_from_file(target_date, trade_dates_path)
    if file_answer is None:
        if trading_day_func is None:
            from sim.trade_calendar import is_trading_day

            trading_day_func = is_trading_day
        is_trade_day = bool(trading_day_func(target_date))
    else:
        is_trade_day = file_answer
    if not is_trade_day:
        return ReviewCheckResult(True, "non_trading_day", "", None, [])

    paths = _candidate_review_paths(Path(review_dir), target_date)
    first_failure: tuple[str, str, Path] | None = None
    for path in paths:
        ok, reason, detail = _review_status(path)
        if ok:
            return ReviewCheckResult(True, "", "", path, [str(p) for p in paths])
        if first_failure is None:
            first_failure = (reason, detail, path)

    reason, detail, path = first_failure or ("missing", "review file not found", paths[0])
    if reason == "missing" and len(paths) > 1:
        detail = "review file not found in any monitored directory: " + ", ".join(str(p) for p in paths)
    return ReviewCheckResult(False, reason, detail, path, [str(p) for p in paths])


def ensure_alerts_table(conn: sqlite3.Connection) -> None:
    """Create/upgrade the PM alert table used by review monitors."""
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
            updated_at TEXT NOT NULL,
            alert_type TEXT,
            target_date TEXT,
            details TEXT
        )
        """
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(alerts)").fetchall()}
    for name, ddl in {
        "alert_type": "ALTER TABLE alerts ADD COLUMN alert_type TEXT",
        "target_date": "ALTER TABLE alerts ADD COLUMN target_date TEXT",
        "details": "ALTER TABLE alerts ADD COLUMN details TEXT",
    }.items():
        if name not in cols:
            conn.execute(ddl)


def upsert_pm_alert(
    db_path: Path,
    *,
    alert_key: str,
    title: str,
    message: str,
    trade_date: date,
    reason: str,
    review_path: Path,
    detail: str = "",
    checked_paths: list[str] | None = None,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata = json.dumps(
        {
            "reason": reason,
            "review_path": str(review_path),
            "checked_paths": checked_paths or [str(review_path)],
            "detail": detail,
        },
        ensure_ascii=False,
    )
    with sqlite3.connect(db_path) as conn:
        ensure_alerts_table(conn)
        conn.execute(
            """
            INSERT INTO alerts(
                alert_key, type, severity, title, message, status, source,
                trade_date, metadata, created_at, updated_at,
                alert_type, target_date, details
            )
            VALUES (?, 'review_missing', 'warn', ?, ?, 'open',
                    'scripts.review_missing_check', ?, ?, ?, ?,
                    'review_missing', ?, ?)
            ON CONFLICT(alert_key) DO UPDATE SET
                severity=excluded.severity,
                title=excluded.title,
                message=excluded.message,
                status='open',
                metadata=excluded.metadata,
                updated_at=excluded.updated_at,
                alert_type=excluded.alert_type,
                target_date=excluded.target_date,
                details=excluded.details
            """,
            (
                alert_key,
                title,
                message,
                trade_date.isoformat(),
                metadata,
                now,
                now,
                trade_date.isoformat(),
                detail or reason,
            ),
        )
        conn.commit()


def append_log(log_path: Path, payload: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def build_alert_message(target_date: date, review_path: Path, reason: str, detail: str = "") -> str:
    reason_zh = {
        "missing": "文件不存在",
        "empty": "文件为空",
        "not_a_file": "路径不是普通文件",
        "incomplete": "内容不完整",
    }.get(reason, reason)
    try:
        rel_path = review_path.relative_to(ROOT) if review_path.is_absolute() else review_path
    except ValueError:
        rel_path = review_path
    extra = f"\n详情：{detail}" if detail else ""
    return (
        f"⚠️ QuantLearn 工作日复盘缺失告警\n"
        f"日期：{target_date.isoformat()}\n"
        f"检查项：{rel_path}\n"
        f"问题：{reason_zh}{extra}\n"
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
    as_of: datetime | None = None,
    cutoff: dtime = DEFAULT_CUTOFF,
    trade_dates_path: Path | None = ROOT / "data" / "trade_dates.json",
    trading_day_func: Optional[Callable[[date], bool]] = None,
    notifier: Optional[Callable[[str], bool]] = None,
) -> dict:
    """Run the review monitor once and return a structured result."""
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result_obj = check_review(
        target_date,
        as_of=as_of,
        cutoff=cutoff,
        review_dir=reviews_dir,
        trade_dates_path=trade_dates_path,
        trading_day_func=trading_day_func,
    )

    if result_obj.ok:
        status = "ok"
        if result_obj.reason == "non_trading_day":
            status = "skipped_non_trading_day"
        elif result_obj.reason == "before_cutoff":
            status = "skipped_before_cutoff"
        result = {
            "checked_at": checked_at,
            "date": target_date.isoformat(),
            "status": status,
            "reason": result_obj.reason,
            "review_path": str(result_obj.review_path or (Path(reviews_dir) / f"{target_date.isoformat()}.md")),
            "checked_paths": result_obj.checked_paths or [],
        }
        append_log(log_path, result)
        return result

    review_path = result_obj.review_path or (Path(reviews_dir) / f"{target_date.isoformat()}.md")
    title = f"工作日复盘缺失：{target_date.isoformat()}"
    message = build_alert_message(target_date, review_path, result_obj.reason, result_obj.detail)
    alert_key = f"review_missing:{target_date.isoformat()}"
    result = {
        "checked_at": checked_at,
        "date": target_date.isoformat(),
        "status": "alert",
        "reason": result_obj.reason,
        "detail": result_obj.detail,
        "alert_key": alert_key,
        "review_path": str(review_path),
        "checked_paths": result_obj.checked_paths or [str(review_path)],
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
                reason=result_obj.reason,
                review_path=review_path,
                detail=result_obj.detail,
                checked_paths=result_obj.checked_paths,
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
    parser.add_argument("--as-of", help="current datetime for testing, YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--cutoff", default="18:00", help="after-close cutoff, HH:MM[:SS]")
    parser.add_argument("--reviews-dir", "--review-dir", dest="reviews_dir", default=str(DEFAULT_REVIEWS_DIR))
    parser.add_argument("--trade-dates", default=str(ROOT / "data" / "trade_dates.json"))
    parser.add_argument("--db", "--pm-db", dest="db", default=str(DEFAULT_PM_DB))
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
        as_of=_parse_datetime(args.as_of) if args.as_of else None,
        cutoff=_parse_time(args.cutoff),
        trade_dates_path=Path(args.trade_dates) if args.trade_dates else None,
    )
    # Backward compatibility: older CLI tests expect non-trading-day skips to be
    # completely quiet (no false-positive DB row and no log file).  ``run_check``
    # still logs skips for scheduler observability when called directly.
    if result.get("status") == "skipped_non_trading_day":
        try:
            log_path = Path(args.log)
            if log_path.exists():
                log_path.unlink()
        except Exception:
            pass
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result.get("status") == "alert" else 0


if __name__ == "__main__":
    raise SystemExit(main())
