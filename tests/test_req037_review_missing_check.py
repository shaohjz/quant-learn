import json
import sqlite3
from datetime import datetime, time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.review_missing_check import check_review, main


def write_calendar(path: Path, dates):
    path.write_text(json.dumps({"dates": dates}, ensure_ascii=False), encoding="utf-8")


def test_workday_after_cutoff_missing_review_records_alert(tmp_path):
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    trade_dates = tmp_path / "trade_dates.json"
    write_calendar(trade_dates, ["2026-05-27"])
    pm_db = tmp_path / "pm.db"
    log_path = tmp_path / "review_missing.log"

    rc = main([
        "--date", "2026-05-27",
        "--as-of", "2026-05-27 18:05:00",
        "--review-dir", str(review_dir),
        "--trade-dates", str(trade_dates),
        "--pm-db", str(pm_db),
        "--log", str(log_path),
    ])

    assert rc == 2
    with sqlite3.connect(pm_db) as conn:
        row = conn.execute("SELECT alert_type, target_date, message, details FROM alerts").fetchone()
    assert row[0] == "review_missing"
    assert row[1] == "2026-05-27"
    assert "missing" in row[2]
    assert "review file not found" in row[3]
    assert "2026-05-27" in log_path.read_text(encoding="utf-8")


def test_non_trading_day_skips_without_false_positive(tmp_path):
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    trade_dates = tmp_path / "trade_dates.json"
    write_calendar(trade_dates, ["2026-05-29"])
    pm_db = tmp_path / "pm.db"
    log_path = tmp_path / "review_missing.log"

    rc = main([
        "--date", "2026-05-30",  # Saturday and not in local trading calendar
        "--as-of", "2026-05-30 18:30:00",
        "--review-dir", str(review_dir),
        "--trade-dates", str(trade_dates),
        "--pm-db", str(pm_db),
        "--log", str(log_path),
    ])

    assert rc == 0
    assert not pm_db.exists()
    assert not log_path.exists()


def test_existing_empty_or_incomplete_review_is_detected(tmp_path):
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    trade_dates = tmp_path / "trade_dates.json"
    write_calendar(trade_dates, ["2026-05-27"])

    empty_file = review_dir / "2026-05-27.md"
    empty_file.write_text("", encoding="utf-8")
    result = check_review(
        target_date=datetime(2026, 5, 27).date(),
        as_of=datetime(2026, 5, 27, 18, 1),
        cutoff=time(18, 0),
        review_dir=review_dir,
        trade_dates_path=trade_dates,
    )
    assert not result.ok
    assert result.reason == "empty"

    empty_file.write_text("# 双账户复盘\n\n只有标题，没有账户表", encoding="utf-8")
    result = check_review(
        target_date=datetime(2026, 5, 27).date(),
        as_of=datetime(2026, 5, 27, 18, 1),
        cutoff=time(18, 0),
        review_dir=review_dir,
        trade_dates_path=trade_dates,
    )
    assert not result.ok
    assert result.reason == "incomplete"
    assert "账户概览" in result.detail


def test_existing_complete_review_ok(tmp_path):
    review_dir = tmp_path / "reviews"
    review_dir.mkdir()
    trade_dates = tmp_path / "trade_dates.json"
    write_calendar(trade_dates, ["2026-05-27"])
    (review_dir / "2026-05-27.md").write_text("# 双账户复盘\n\n## 一、账户概览\n|账户|总资产|", encoding="utf-8")

    result = check_review(
        target_date=datetime(2026, 5, 27).date(),
        as_of=datetime(2026, 5, 27, 18, 1),
        cutoff=time(18, 0),
        review_dir=review_dir,
        trade_dates_path=trade_dates,
    )

    assert result.ok
    assert result.reason == ""
