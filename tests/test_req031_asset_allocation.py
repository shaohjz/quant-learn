from __future__ import annotations

from sim.asset_allocation import (
    classify_asset_class,
    classify_strategy_bucket,
    infer_market_regime,
    render_allocation_markdown,
    summarize_allocation,
)


def test_classify_asset_class_etf_and_fixed_income():
    assert classify_asset_class({"stock_code": "510300", "stock_name": "沪深300ETF"}) == "宽基/行业ETF"
    assert classify_asset_class({"stock_code": "511880", "stock_name": "银华日利"}) == "固收/现金管理"
    assert classify_asset_class({"stock_code": "600330", "stock_name": "天通股份"}) == "个股量化"


def test_strategy_bucket_uses_latest_buy_context():
    trade = {"direction": "BUY", "trade_context": '{"strategy":"grid","buy_type":"buy_zone"}', "signal_reason": "网格低吸"}
    assert classify_strategy_bucket({"stock_code": "600330"}, trade) == "网格"
    assert classify_strategy_bucket({"stock_code": "002001"}, {"signal_reason": "涨停打板强势确认"}) == "打板/强势"
    assert classify_strategy_bucket({"stock_code": "000001"}, {"signal_reason": "手动买入"}) == "主观/手动"


def test_infer_market_regime_from_label_and_breadth():
    assert infer_market_regime({"risk_label": "偏弱/注意跌停扩散"}) == "weak"
    assert infer_market_regime({"risk_label": "偏强/情绪活跃"}) == "strong"
    assert infer_market_regime({"up_count": 3000, "down_count": 1000}) == "strong"
    assert infer_market_regime({"up_count": 1000, "down_count": 3000}) == "weak"


def test_summarize_allocation_generates_reduce_advice_in_weak_market():
    account = {"id": 1, "cash": 10_000, "initial_cash": 100_000}
    positions = [
        {"stock_code": "600330", "stock_name": "天通股份", "quantity": 1000, "current_price": 40, "market_value": 40_000},
        {"stock_code": "510300", "stock_name": "沪深300ETF", "quantity": 1000, "current_price": 50, "market_value": 50_000},
    ]
    trades = [
        {"stock_code": "600330", "direction": "BUY", "created_at": "2026-05-01", "signal_reason": "趋势突破"},
        {"stock_code": "510300", "direction": "BUY", "created_at": "2026-05-02", "signal_reason": "低吸配置"},
    ]
    out = summarize_allocation(account, positions, trades, {"risk_label": "偏弱"})
    assert out["market_regime"] == "weak"
    assert out["position_pct"] == 90.0
    assert any("建议调降" in item for item in out["advice"])
    assert {r["name"] for r in out["asset_classes"]} >= {"个股量化", "宽基/行业ETF", "现金"}
    md = render_allocation_markdown(out)
    assert "大类资产配置" in md
    assert "策略占用" in md
