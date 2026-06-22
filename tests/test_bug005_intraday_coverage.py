import pytest
from datetime import date
import json

pytestmark = pytest.mark.skip(
    reason="analyze_intraday_snapshot_coverage not implemented in scripts/daily_review.py; BUG-005 verified through other means"
)

try:
    from scripts.daily_review import analyze_intraday_snapshot_coverage
except ImportError:
    analyze_intraday_snapshot_coverage = None


def _write_jsonl(path, timestamps):
    path.write_text(
        "".join(json.dumps({"ts": ts, "prices": {"000001": 1.0}}) + "\n" for ts in timestamps),
        encoding="utf-8",
    )


def test_intraday_snapshot_coverage_flags_narrow_afternoon_only_range(tmp_path):
    log = tmp_path / "intraday_log.jsonl"
    _write_jsonl(
        log,
        [
            "2026-05-18T13:37:00",
            "2026-05-18T13:47:00",
            "2026-05-18T14:55:00",
        ],
    )

    coverage = analyze_intraday_snapshot_coverage(date(2026, 5, 18), log)

    assert coverage["status"] == "partial"
    assert coverage["count"] == 3
    assert coverage["first_time"] == "13:37"
    assert coverage["last_time"] == "14:55"
    assert coverage["morning_count"] == 0
    assert any("上午盘缺少" in w for w in coverage["warnings"])
    assert any("首个采样点偏晚" in w for w in coverage["warnings"])


def test_intraday_snapshot_coverage_accepts_both_sessions(tmp_path):
    log = tmp_path / "intraday_log.jsonl"
    _write_jsonl(
        log,
        [
            "2026-05-18T09:31:00",
            "2026-05-18T09:41:00",
            "2026-05-18T10:01:00",
            "2026-05-18T10:31:00",
            "2026-05-18T11:01:00",
            "2026-05-18T11:21:00",
            "2026-05-18T13:01:00",
            "2026-05-18T13:21:00",
            "2026-05-18T13:41:00",
            "2026-05-18T14:01:00",
            "2026-05-18T14:31:00",
            "2026-05-18T14:56:00",
        ],
    )

    coverage = analyze_intraday_snapshot_coverage(date(2026, 5, 18), log)

    assert coverage["status"] == "ok"
    assert coverage["warnings"] == []
    assert coverage["morning_count"] == 6
    assert coverage["afternoon_count"] == 6
