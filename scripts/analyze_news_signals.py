# -*- coding: utf-8 -*-
"""对今日新闻信号进行利好/利空/中性分类并更新 DB。"""
import json
import sqlite3
import re

DB_PATH = r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db"
JSON_PATH = r"C:\Users\Administrator\.openclaw\workspace\quant-learn\output\news_signals_2026-07-12.json"

# ---- 分类规则（按优先级匹配）----
# 利空关键词
SELL_PATTERNS = [
    "下跌", "跌停", "大跌", "跳水", "净流出", "撤离", "减持", "处罚", "诉讼", "立案",
    "下滑", "亏损", "预减", "风险", "质押", "终止", "死叉", "利空", "封跌停", "蒸发",
    "连续降", "减仓", "缩水", "连降", "下修", "警示", "问询", "监管",
]
# 利好关键词
BUY_PATTERNS = [
    "预增", "增长", "同比增长", "大增", "净利预增", "净利润同比", "分红", "派发", "派息",
    "回购", "收购", "并购", "中标", "签下", "签订", "大单", "订单", "扩产", "突破",
    "涨停", "大涨", "净流入", "创新高", "新高", "利好", "增资", "获批", "批复",
    "强势", "爆发", "集体爆发", "复牌", "扭亏", "历史新高", "大涨", "走强", "全线走强",
    "龙虎榜抢筹", "抢筹", "加急补货", "卖断货", "海外", "认可", "样机", "落地",
]

# 一些需要排除的中性/混合词（出现在标题中不单独构成利好）
NEUTRAL_TITLES = [
    "资金流向日报", "大宗交易成交明细", "盘中播报", "短线防风险", "主力资金连续",
    "创业板公司融资余额", "两融余额", "短线走稳", "长线走稳", "突破年线", "站上年线",
    "站上五日均线", "基金最新动向", "机构密集调研", "强势股追踪", "个股短期均线现死叉",
]


def classify(title, source):
    t = title
    # 1) 中性：明确的数据汇总/资讯类标题
    for nt in NEUTRAL_TITLES:
        if nt in t:
            # 但如果同时含明显利好词（如净流入且涨），仍判利好
            if any(p in t for p in ["净流入", "涨", "爆发", "走强"]):
                return "BUY", 0.6, "板块资金净流入/走强"
            return "HOLD", 0.5, "资讯/资金流向数据，无明确多空倾向"

    # 2) 先判利空
    sell_hits = [p for p in SELL_PATTERNS if p in t]
    # 3) 再判利好
    buy_hits = [p for p in BUY_PATTERNS if p in t]

    # 资金净流出 / 撤离 / 下跌 → 利空
    if sell_hits and not buy_hits:
        return "SELL", 0.7, "利空：" + "、".join(sell_hits[:3])
    if buy_hits and not sell_hits:
        return "BUY", 0.8, "利好：" + "、".join(buy_hits[:3])
    if buy_hits and sell_hits:
        # 同时出现，看哪类更主导
        # 业绩增长类强利好优先
        strong_buy = ["预增", "增长", "同比增长", "净利预增", "净利润同比", "分红", "派发",
                      "回购", "收购", "并购", "中标", "签下", "签订", "大单", "订单",
                      "涨停", "创新高", "历史新高", "复牌", "爆发", "集体爆发", "走强",
                      "全线走强", "龙虎榜抢筹", "抢筹", "扭亏"]
        if any(p in t for p in strong_buy):
            return "BUY", 0.75, "利好主导：" + "、".join([p for p in buy_hits if p in strong_buy][:3])
        return "HOLD", 0.5, "多空信息交织，倾向中性"
    # 4) 都不匹配
    return "HOLD", 0.5, "信息中性或倾向不明确"


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    signals = data["signals"]

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    for s in signals:
        sid = s["id"]
        title = s.get("title", "")
        source = s.get("source", "")
        action, conf, reason = classify(title, source)
        c.execute(
            "UPDATE strategy_shadow_signals SET signal_action=?, confidence=?, signal_reason=? WHERE id=?",
            (action, conf, reason, sid),
        )
        counts[action] += 1
        print(f"id={sid} [{action}] {title[:40]} -> {reason}")

    conn.commit()
    conn.close()
    print("\n==== 汇总 ====")
    print(f"BUY(利好)={counts['BUY']}  SELL(利空)={counts['SELL']}  HOLD(中性)={counts['HOLD']}  总计={sum(counts.values())}")
    # 写出汇总供推送使用
    with open(r"C:\Users\Administrator\.openclaw\workspace\quant-learn\output\news_analysis_summary.txt", "w", encoding="utf-8") as f:
        f.write(f"{counts['BUY']}|{counts['SELL']}|{counts['HOLD']}")


if __name__ == "__main__":
    main()
