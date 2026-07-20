"""波段日报：结论结构与挂单建议（无行情）。"""

from scripts.swing_daily_report import (
    build_conclusion,
    load_intraday_buy_alerts,
    merge_buys,
    pick_buys,
    render_markdown,
)


def test_pick_buys_only_ab_high_score():
    scan = [
        {"code": "sh600036", "name": "招商银行", "price": 35.0, "score": 6,
         "signal_type": "A", "support": 34.0, "resist": 37.0, "net_rr": 1.8},
        {"code": "sz000651", "name": "格力电器", "price": 40.0, "score": 7,
         "signal_type": "C", "support": 39.0, "resist": 42.0, "net_rr": 2.0},
    ]
    picks = pick_buys(scan, [])
    assert len(picks) == 1
    assert picks[0]["code"] == "600036"


def test_merge_buys_intraday_first():
    scan = pick_buys(
        [{"code": "sh600036", "name": "招商银行", "price": 35.0, "score": 6,
          "signal_type": "A", "support": 34.0, "resist": 37.0, "net_rr": 1.8}],
        [],
    )
    intra = [{
        "code": "300059", "name": "东方财富", "price": 20.08, "score": 7,
        "signal_type": "A", "support": 20.04, "resist": 20.38, "net_rr": 1.23,
        "stop": 19.64, "target": 20.38, "from_intraday": True,
    }]
    merged = merge_buys(scan, intra, [])
    assert merged[0]["code"] == "300059"
    assert merged[0].get("from_intraday") is True
    assert any(x["code"] == "600036" for x in merged)


def test_load_intraday_buy_alerts(tmp_path, monkeypatch):
    import scripts.swing_daily_report as m

    out = tmp_path / "output" / "swing_intraday"
    out.mkdir(parents=True)
    day = "2026-07-20"
    (out / f"{day}.log").write_text(
        '2026-07-20T10:05:00 BUY:300059 {"kind":"BUY","code":"300059","name":"东方财富",'
        '"price":20.08,"score":7,"signal_type":"A","support":20.04,"resist":20.38,'
        '"net_rr":1.23,"stop":19.64,"target":20.38}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(m, "ROOT", tmp_path)
    alerts = load_intraday_buy_alerts(day)
    assert len(alerts) == 1
    assert alerts[0]["code"] == "300059"
    assert alerts[0]["from_intraday"] is True


def test_verdict_and_advice():
    snap = {
        "cash": 90000, "market_value": 10000, "total": 100500,
        "cum_pnl": 500, "cum_pct": 0.5, "positions": [],
    }
    fills = [
        {"ok": True, "side": "BUY", "code": "600900", "name": "长江电力",
         "qty": 300, "price": 28.0, "reason": "A分7", "stop": 26.6, "target": 30.24},
    ]
    c = build_conclusion("2026-07-14", snap, fills, [], day_pnl=120.0, day_pct=0.12)
    assert "赚" in c["verdict"]
    assert any(a["action"] == "BUY" for a in c["advice"])
    md = render_markdown(c)
    assert "给你挂单建议" in md
    assert "波段结论" in md


def test_loss_verdict():
    snap = {
        "cash": 80000, "market_value": 18000, "total": 98000,
        "cum_pnl": -2000, "cum_pct": -2.0,
        "positions": [{"code": "600519", "name": "茅台", "qty": 10, "cost": 1600,
                      "price": 1500, "pnl_pct": -6.25, "stop": 1520, "target": 1728}],
    }
    fills = [
        {"ok": True, "side": "SELL", "code": "600809", "name": "汾酒",
         "qty": 100, "price": 100.0, "realized": -300.0, "reason": "止损@105"},
    ]
    c = build_conclusion("2026-07-14", snap, fills, [], day_pnl=-800.0, day_pct=-0.8)
    assert "亏" in c["verdict"]
    assert any(a["action"] == "SELL" for a in c["advice"])
