from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from scripts.review_missing_check import run_check


def _read_alerts(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM alerts ORDER BY id")]
    finally:
        conn.close()


def test_trading_day_missing_review_writes_alert_log_and_pushes(tmp_path):
    reviews = tmp_path / "reviews"
    db_path = tmp_path / "pm.db"
    log_path = tmp_path / "review_missing.log"
    sent: list[str] = []

    result = run_check(
        date(2026, 5, 27),
        reviews_dir=reviews,
        db_path=db_path,
        log_path=log_path,
        trading_day_func=lambda d: True,
        notifier=lambda text: sent.append(text) or True,
    )

    assert result["status"] == "alert"
    assert result["reason"] == "missing"
    assert result["pushed"] is True
    assert sent and "2026-05-27" in sent[0]
    assert "文件不存在" in sent[0]
    alerts = _read_alerts(db_path)
    assert len(alerts) == 1
    assert alerts[0]["alert_key"] == "review_missing:2026-05-27"
    assert alerts[0]["type"] == "review_missing"
    assert alerts[0]["status"] == "open"
    assert "2026-05-27" in alerts[0]["message"]
    assert log_path.exists()
    assert "alert" in log_path.read_text(encoding="utf-8")


def test_non_trading_day_does_not_alert(tmp_path):
    sent: list[str] = []
    result = run_check(
        date(2026, 5, 31),
        reviews_dir=tmp_path / "reviews",
        db_path=tmp_path / "pm.db",
        log_path=tmp_path / "review_missing.log",
        trading_day_func=lambda d: False,
        notifier=lambda text: sent.append(text) or True,
    )

    assert result["status"] == "skipped_non_trading_day"
    assert sent == []
    assert not (tmp_path / "pm.db").exists()
    assert "skipped_non_trading_day" in (tmp_path / "review_missing.log").read_text(encoding="utf-8")


def test_empty_review_file_is_alerted(tmp_path):
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / "2026-05-27.md").write_text("  \n\t", encoding="utf-8")

    result = run_check(
        date(2026, 5, 27),
        reviews_dir=reviews,
        db_path=tmp_path / "pm.db",
        log_path=tmp_path / "review_missing.log",
        trading_day_func=lambda d: True,
        notifier=lambda text: True,
    )

    assert result["status"] == "alert"
    assert result["reason"] == "empty"
    alerts = _read_alerts(tmp_path / "pm.db")
    assert len(alerts) == 1
    assert "文件为空" in alerts[0]["message"]


def test_non_empty_review_file_is_ok_without_alert(tmp_path):
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / "2026-05-27.md").write_text("# 复盘\n\n有内容", encoding="utf-8")
    sent: list[str] = []

    result = run_check(
        date(2026, 5, 27),
        reviews_dir=reviews,
        db_path=tmp_path / "pm.db",
        log_path=tmp_path / "review_missing.log",
        trading_day_func=lambda d: True,
        notifier=lambda text: sent.append(text) or True,
    )

    assert result["status"] == "ok"
    assert sent == []
    assert not (tmp_path / "pm.db").exists()
    assert "ok" in (tmp_path / "review_missing.log").read_text(encoding="utf-8")


def test_default_monitor_accepts_active_output_reviews_dir(tmp_path, monkeypatch):
    """BUG-018: active daily_review.py writes output/reviews, not docs/reviews."""
    monkeypatch.setattr("scripts.review_missing_check.DEFAULT_REVIEWS_DIR", tmp_path / "output" / "reviews")
    monkeypatch.setattr("scripts.review_missing_check.LEGACY_REVIEWS_DIR", tmp_path / "docs" / "reviews")
    (tmp_path / "output" / "reviews").mkdir(parents=True)
    (tmp_path / "output" / "reviews" / "2026-05-27.md").write_text(
        "# 📊 2026/5/27 日复盘\n\n## 🤖 学习账户\n有内容",
        encoding="utf-8",
    )
    sent: list[str] = []

    result = run_check(
        date(2026, 5, 27),
        reviews_dir=tmp_path / "output" / "reviews",
        db_path=tmp_path / "pm.db",
        log_path=tmp_path / "review_missing.log",
        trading_day_func=lambda d: True,
        notifier=lambda text: sent.append(text) or True,
    )

    assert result["status"] == "ok"
    assert result["review_path"].endswith("output\\reviews\\2026-05-27.md") or result["review_path"].endswith("output/reviews/2026-05-27.md")
    assert sent == []
    assert not (tmp_path / "pm.db").exists()
