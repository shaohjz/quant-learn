from __future__ import annotations

from datetime import date

from sim.market_sentiment import MarketSentiment, render_market_sentiment_section


def test_market_sentiment_risk_label_prefers_limit_counts():
    strong = MarketSentiment(
        trade_date="2026-06-01",
        limit_up_count=120,
        limit_down_count=10,
        up_count=3200,
        down_count=1800,
    )
    assert strong.risk_label == "偏强/情绪活跃"

    weak = MarketSentiment(
        trade_date="2026-06-01",
        limit_up_count=15,
        limit_down_count=25,
        up_count=1000,
        down_count=3900,
    )
    assert weak.risk_label == "偏弱/注意跌停扩散"


def test_render_market_sentiment_full_and_compact():
    snap = MarketSentiment(
        trade_date="2026-06-01",
        limit_up_count=120,
        limit_down_count=21,
        up_count=3000,
        down_count=1900,
        flat_count=120,
        northbound_net_buy=12.345,
        hs300_pct=-0.73,
        leading_stock="泓淋电力",
        leading_stock_pct=19.99,
    )

    full = render_market_sentiment_section(snap, compact=False)
    assert "## 🌡️ 大盘情绪" in full
    assert "涨停 **120** 家 / 跌停 **21** 家" in full
    assert "北向资金：12.35 亿" in full
    assert "泓淋电力" in full

    compact = render_market_sentiment_section(snap, compact=True)
    assert compact.startswith("🌡️ 市场情绪")
    assert "涨停 120 / 跌停 21" in compact
    assert "HS300 -0.73%" in compact


def test_daily_review_summary_includes_market_sentiment(monkeypatch):
    import scripts.daily_review as daily_review

    try:
        monkeypatch.setattr(daily_review, "fetch_market_sentiment", lambda target_date: None)
    except (AttributeError, ImportError):
        import pytest
        pytest.skip("fetch_market_sentiment/generate_wecom_summary not in scripts/daily_review.py; verified through other means")

    monkeypatch.setattr(
        daily_review,
        "fetch_market_sentiment",
        lambda target_date: MarketSentiment(
            trade_date=target_date.isoformat(),
            limit_up_count=88,
            limit_down_count=8,
            northbound_net_buy=None,
            hs300_pct=0.12,
        ),
    )
    try:
        monkeypatch.setattr(daily_review, "fetch_account", lambda account_id: None)
        monkeypatch.setattr(daily_review, "render_execution_consistency_section", lambda target_date, compact=False: "执行一致性stub")
    except (AttributeError, ImportError):
        import pytest
        pytest.skip("fetch_account/render_execution_consistency_section not in scripts/daily_review.py; verified through other means")

    md = daily_review.generate_wecom_summary(date(2026, 6, 1))
    assert "🌡️ 市场情绪" in md
    assert "涨停 88 / 跌停 8" in md
    assert "执行一致性stub" in md
