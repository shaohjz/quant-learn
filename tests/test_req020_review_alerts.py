from __future__ import annotations

from datetime import date

from scripts.daily_review import detect_trade_anomaly_alerts, format_review_alerts


def test_req020_detects_position_loss_and_trade_anomalies():
    account = {"cash": 40000}
    positions = [
        {
            "stock_code": "600000",
            "stock_name": "浦发银行",
            "quantity": 1000,
            "market_value": 60000,
            "pnl": -7200,
            "pnl_pct": -12.0,
        }
    ]
    trades = [
        {"direction": "BUY", "stock_code": "600000", "price": 10.0, "quantity": 3000, "amount": 30000},
        {"direction": "SELL", "stock_code": "000001", "price": 20.0, "quantity": 1000, "amount": 20000},
    ]
    realized = [{"pnl": -1500}]
    nav = {"total_value": 100000, "daily_return": -3.5, "max_drawdown": -11.0}

    alerts = detect_trade_anomaly_alerts(
        account,
        positions,
        trades,
        realized,
        nav,
        date(2026, 6, 1),
        thresholds={
            "position_loss_pct": -0.10,
            "watch_loss_pct": -0.05,
            "daily_return_drop_pct": -0.03,
            "drawdown_pct": -0.10,
            "realized_loss_pct_of_assets": 0.01,
            "large_trade_pct_of_assets": 0.20,
            "large_position_pct_of_assets": 0.35,
            "max_trade_count": 1,
        },
    )

    kinds = {a["kind"] for a in alerts}
    assert "position_stop_loss" in kinds
    assert "position_concentration" in kinds
    assert "daily_nav_drop" in kinds
    assert "drawdown" in kinds
    assert "realized_loss" in kinds
    assert "trade_count_spike" in kinds
    assert "large_turnover" in kinds

    rendered = format_review_alerts(alerts, compact=False)
    assert "异动/警示" in rendered
    assert "浦发银行(600000) 浮亏 -12.00%" in rendered
    assert "账户当日收益 -3.50%" in rendered


def test_req020_compact_alert_render_limits_output():
    alerts = [
        {"severity": "warn", "kind": f"k{i}", "message": f"alert-{i}"}
        for i in range(5)
    ]
    rendered = format_review_alerts(alerts, compact=True, limit=2)
    assert rendered.startswith("⚠️ 异动/警示")
    assert "alert-0" in rendered
    assert "alert-1" in rendered
    assert "alert-2" not in rendered
    assert "另有 3 条" in rendered
