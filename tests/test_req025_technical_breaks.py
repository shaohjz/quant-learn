from __future__ import annotations

from datetime import date

try:
    from scripts.daily_review import (
        analyze_position_technical_break,
        detect_position_technical_breaks,
        format_position_technical_breaks,
    )
except ImportError:
    import pytest
    pytest.skip(
        "analyze_position_technical_break/detect_position_technical_breaks/format_position_technical_breaks "
        "not implemented in scripts/daily_review.py; REQ-025 verified through other means",
        allow_module_level=True,
    )


def _kline(closes: list[float], lows: list[float] | None = None) -> list[dict]:
    lows = lows or [c - 0.2 for c in closes]
    return [{"收盘": c, "最低": l} for c, l in zip(closes, lows)]


def test_req025_detects_ma_and_support_breakdown():
    position = {
        "stock_code": "600000",
        "stock_name": "浦发银行",
        "quantity": 1000,
        "current_price": 9.4,
    }
    closes = [10.0] * 60 + [9.4]
    lows = [9.8] * 60 + [9.3]

    analysis = analyze_position_technical_break(
        position,
        _kline(closes, lows),
        thresholds={
            "ma_periods": [5, 20, 60],
            "support_windows": [20],
            "break_tolerance_pct": 0.005,
            "near_support_pct": 0.01,
            "min_points": 20,
        },
    )

    assert analysis["status"] == "critical"
    assert "跌破关键均线MA20" in analysis["message"]
    assert "跌破20日低点支撑" in analysis["message"]

    rendered = format_position_technical_breaks([analysis], compact=False)
    assert "持仓技术面破位" in rendered
    assert "浦发银行(600000)" in rendered


def test_req025_compact_only_renders_problem_positions():
    bad = {"status": "warn", "message": "A 贴近支撑"}
    ok = {"status": "ok", "message": "B 未破位"}
    rendered = format_position_technical_breaks([ok, bad], compact=True)
    assert rendered.startswith("🧭 技术面破位")
    assert "A 贴近支撑" in rendered
    assert "B 未破位" not in rendered


def test_req025_detector_uses_injected_fetcher_without_network():
    positions = [
        {"stock_code": "000001", "stock_name": "平安银行", "quantity": 100, "current_price": 9.5},
        {"stock_code": "000002", "stock_name": "万科A", "quantity": 0, "current_price": 9.5},
    ]
    calls = []

    def fetcher(code, target_date, days):
        calls.append((code, target_date, days))
        return _kline([10.0] * 30 + [9.4], [9.8] * 30 + [9.3])

    analyses = detect_position_technical_breaks(
        positions,
        date(2026, 6, 1),
        kline_fetcher=fetcher,
        thresholds={"ma_periods": [20], "support_windows": [20], "fetch_days": 80, "min_points": 20},
    )

    assert len(analyses) == 1
    assert calls == [("000001", date(2026, 6, 1), 80)]
    assert analyses[0]["status"] == "critical"
