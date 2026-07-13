#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析今日新闻信号，判断利好/利空/中性并写入 sim_live_mirror.db。"""
import sqlite3
import json
import os
import re

BASE = r"C:\Users\Administrator\.openclaw\workspace\quant-learn"
JSON_PATH = os.path.join(BASE, "output", "news_signals_2026-07-08.json")
DB_PATH = os.path.join(BASE, "data", "sim_live_mirror.db")

# ---------- 关键词分类 ----------
BUY_KW = [
    "签下", "签订", "大单", "采购合同", "订单", "中标", "分红", "派息", "派现",
    "回购", "增持", "涨停", "创新高", "历史新高", "新高", "突破", "爆发", "集体爆发",
    "增长", "大增", "扭亏", "盈利", "净利润", "营收", "业绩", "利好", "拉升", "涨近",
    "净流入", "资金流入", "机构大买", "融资客大举买入", "大手笔净买入", "获融资客",
    "扩产", "投产", "项目落地", "合同", "上调", "中标", "销冠", "全球销冠", "突破年线",
    "站上年线", "长线走稳", "强势", "拟收购", "购买资产", "并购", "切入", "完成回购",
    "股权登记", "权益分派", "龙虎榜抢筹", "抢筹", "主力资金净流入", "资金净流入",
    "大涨", "盘中涨", "概念涨", "行业涨", "板块涨", "政策利好", "中标通知书",
]

SELL_KW = [
    "跌停", "封跌停", "跳水", "大跌", "下跌风险", "回落风险", "可能快速回落",
    "风险提示", "监管处罚", "处罚", "被罚", "立案", "诉讼", "减持", "质押", "冻结",
    "停产", "断供", "终止", "违约", "亏损", "下滑", "下修", "预减", "计提减值",
    "资金流出", "净流出", "主力资金净流出", "出逃", "连续净流出", "死叉", "跌超",
    "盘中跌", "概念下跌", "行业跌", "板块下跌", "大幅下跌", "利空", "风险",
    "短线防风险", "三连降", "连续下降", "缩水", "跌7", "跌停潮",
    "借户炒股", "违规",
]

# 需要谨慎判断的中性/弱信号词（命中但无强多空词时归为 HOLD）
NEUTRAL_KW = [
    "资金流向日报", "大宗交易", "龙虎榜数据", "成立新公司", "成立投资公司",
    "董事会换届", "辞任", "当选董事长", "连任", "注册\"", "商标", "出资参与",
    "参与投资私募基金", "参投", "向全资子公司增资", "调整定增", "调整募投",
    "测试验证", "积极配合客户", "回应", "盘中速报", "盘中播报",
]

def classify(title: str):
    t = title
    buy_hits = [k for k in BUY_KW if k in t]
    sell_hits = [k for k in SELL_KW if k in t]

    # 冲突消解：统计命中数量与权重
    # 利空关键词权重稍高，因风险类消息更明确
    if sell_hits and not buy_hits:
        return "SELL", 0.75, "利空：" + "、".join(sell_hits[:3])
    if buy_hits and not sell_hits:
        return "BUY", 0.78, "利好：" + "、".join(buy_hits[:3])
    if buy_hits and sell_hits:
        # 同时命中，看谁更具体。优先看是否含明确利空风险词
        strong_sell = [k for k in sell_hits if k in ("跌停", "封跌停", "跳水", "大跌", "下跌风险",
                                                       "可能快速回落", "停产", "断供", "终止", "被罚", "处罚",
                                                       "立案", "诉讼", "减持", "质押", "亏损", "下滑", "违约",
                                                       "资金净流出", "主力资金净流出", "出逃", "死叉")]
        strong_buy = [k for k in buy_hits if k in ("签下", "签订", "大单", "采购合同", "订单", "中标",
                                                    "分红", "派息", "回购", "增持", "涨停", "创新高",
                                                    "历史新高", "新高", "增长", "大增", "扭亏", "盈利",
                                                    "净利润", "营收", "业绩", "利好", "扩产", "拟收购",
                                                    "购买资产", "并购", "权益分派")]
        if strong_sell and not strong_buy:
            return "SELL", 0.7, "利空（冲突偏空）：" + "、".join(strong_sell[:3])
        if strong_buy and not strong_sell:
            return "BUY", 0.7, "利好（冲突偏多）：" + "、".join(strong_buy[:3])
        # 都弱 -> 中性
        return "HOLD", 0.5, "多空信号冲突，信息不明确"
    # 无命中
    return "HOLD", 0.45, "无明确利好利空，信息中性"


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    signals = data.get("signals", [])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 确认表存在目标字段
    c.execute("PRAGMA table_info(strategy_shadow_signals)")
    cols = [r[1] for r in c.fetchall()]
    need_cols = ["signal_action", "confidence", "signal_reason"]
    for col in need_cols:
        if col not in cols:
            c.execute(f"ALTER TABLE strategy_shadow_signals ADD COLUMN {col} TEXT")

    stats = {"BUY": 0, "SELL": 0, "HOLD": 0}
    updated = 0
    for s in signals:
        sid = s["id"]
        action, conf, reason = classify(s["title"])
        stats[action] += 1
        c.execute(
            "UPDATE strategy_shadow_signals SET signal_action=?, confidence=?, signal_reason=? WHERE id=?",
            (action, conf, reason, sid),
        )
        updated += 1

    conn.commit()
    conn.close()

    print(f"已更新 {updated} 条信号")
    print(f"BUY={stats['BUY']} SELL={stats['SELL']} HOLD={stats['HOLD']}")
    return stats, updated


if __name__ == "__main__":
    main()
