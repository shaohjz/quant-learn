"""盘中波段盯盘：去重 key 与文案（无行情）。"""

from scripts.swing_intraday_watch import already_fired, format_alert, load_state, mark_fired


def test_dedup_fire_once():
    state = {"date": "2026-07-14", "fired": []}
    assert not already_fired(state, "BUY:600900")
    mark_fired(state, "BUY:600900")
    assert already_fired(state, "BUY:600900")


def test_buy_alert_text_has_order_hint():
    md = format_alert(
        {
            "kind": "BUY",
            "code": "600900",
            "name": "长江电力",
            "price": 28.1,
            "score": 7,
            "signal_type": "A",
            "net_rr": 2.0,
            "risk_reward": 2.1,
            "upside_pct": 4.5,
            "downside_pct": 2.0,
            "fee_ratio": 0.12,
            "support": 27.5,
            "resist": 29.5,
            "support_name": "MA20",
            "resist_name": "MA5",
            "suggested_shares": 300,
            "suggested_amount": 8430.0,
            "signals": "缩量回踩MA20",
            "msg": "限价 27.5~28.1 介入",
            "stop": 26.95,
            "target": 29.5,
        },
        "10:30",
    )
    assert "挂单建议" in md
    assert "长江电力" in md
    assert "盘中波段买入提醒" in md
    assert "预期涨" in md
    assert "毛盈亏比" in md
    assert "手续费约" in md
    assert "建议仓位" in md
    assert "技术位" in md


def test_buy_alert_shows_sim_fill():
    md = format_alert(
        {
            "kind": "BUY",
            "code": "300059",
            "name": "东方财富",
            "price": 20.08,
            "score": 7,
            "signal_type": "A",
            "net_rr": 1.23,
            "signals": "缩量回踩MA20",
            "msg": "限价 20.04~20.08 介入",
            "stop": 19.64,
            "target": 20.38,
            "sim_fill": {
                "ok": True,
                "side": "BUY",
                "qty": 400,
                "price": 20.08,
                "stop": 19.08,
                "target": 21.69,
            },
        },
        "10:05",
    )
    assert "模拟已买" in md
    assert "400股" in md


def test_sell_alert_text():
    md = format_alert(
        {
            "kind": "SELL_STOP",
            "code": "600036",
            "name": "招商银行",
            "price": 33.0,
            "pnl_pct": -5.5,
            "stop": 33.2,
            "target": 37.8,
            "msg": "止损线破位：建议卖出挂单 ~33.00",
        },
        "14:10",
    )
    assert "止损" in md
    assert "招商银行" in md
