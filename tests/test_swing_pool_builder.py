"""动态稳定波段池：过滤 / 打分 / 方法入池+软上限（无行情）。"""

from scripts.swing_pool_builder import (
    churn,
    hard_filter_kline,
    hard_filter_spot,
    select_pool,
    stability_score,
)


def test_hard_filter_spot_rejects_st_and_illiquid():
    assert hard_filter_spot("ST国华", 10.0, 2e8) == "ST"
    assert hard_filter_spot("测试", 3.0, 2e8) == "price"
    assert hard_filter_spot("测试", 10.0, 1e7) == "amount"
    assert hard_filter_spot("长江电力", 28.0, 2e8) is None


def test_hard_filter_kline_atr_band():
    assert hard_filter_kline(1.0, 3.0, -2.0) == "atr"
    assert hard_filter_kline(8.0, 3.0, -2.0) == "atr"
    assert hard_filter_kline(3.0, 8.0, -2.0) == "amp"
    assert hard_filter_kline(3.0, 3.0, -10.0) == "drop"
    assert hard_filter_kline(3.0, 3.0, -2.0) is None


def test_stability_score_prefers_sweet_atr():
    sweet = stability_score(3.0, 2.5, 5e8, -1.0)
    wild = stability_score(5.4, 2.5, 5e8, -1.0)
    assert sweet > wild


def test_select_pool_min_score_and_max_cap():
    cands = [
        {"code": "600900", "name": "长江电力", "stability_score": 80, "protected": False},
        {"code": "600036", "name": "招商银行", "stability_score": 70, "protected": False},
        {"code": "000001", "name": "平安银行", "stability_score": 90, "protected": False},
        {"code": "601318", "name": "中国平安", "stability_score": 60, "protected": False},
        {"code": "600519", "name": "贵州茅台", "stability_score": 65, "protected": False},
    ]
    # 持仓 601318 分低也要进；min_score=70 → 601318保护 + 90/80/70 三只，max=3 → 保护1+最高2
    pool = select_pool(cands, held={"601318"}, max_pool=3, min_score=70)
    codes = [x["code"] for x in pool]
    assert "601318" in codes
    assert any(x.get("protected") for x in pool if x["code"] == "601318")
    assert "000001" in codes  # 最高分
    assert "600519" not in codes  # 65 < 70
    assert "601318" in codes and len(pool) == 3


def test_select_pool_all_passers_under_cap():
    cands = [
        {"code": "600900", "name": "A", "stability_score": 80, "protected": False},
        {"code": "600036", "name": "B", "stability_score": 75, "protected": False},
        {"code": "000001", "name": "C", "stability_score": 72, "protected": False},
    ]
    pool = select_pool(cands, held=set(), max_pool=50, min_score=70)
    assert len(pool) == 3  # 全部合格，不硬卡 TopN


def test_estimate_amount_from_kline():
    from scripts.swing_pool_builder import estimate_amount_from_kline

    klines = [
        {"close": 10.0, "volume": 1000},  # 手 → 1000*100*10 = 1e6
        {"close": 10.0, "volume": 2000},
        {"close": 10.0, "volume": 3000},
        {"close": 10.0, "volume": 4000},
        {"close": 10.0, "volume": 5000},
    ]
    amt = estimate_amount_from_kline(klines, days=5)
    assert amt == (1000 + 2000 + 3000 + 4000 + 5000) / 5 * 100 * 10


def test_churn_entered_exited():
    c = churn({"600900", "600036"}, {"600900", "000001"})
    assert c["entered"] == ["000001"]
    assert c["exited"] == ["600036"]
    assert c["kept"] == ["600900"]
