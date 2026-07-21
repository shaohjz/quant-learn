# -*- coding: utf-8 -*-
"""分析今日新闻信号并写入 DB"""
import sqlite3, json

DB = r"C:\Users\Administrator\.openclaw\workspace\quant-learn\data\sim_live_mirror.db"
JSON_PATH = r"C:\Users\Administrator\.openclaw\workspace\quant-learn\output\news_signals_2026-07-17.json"

# 分析函数：根据标题判断利好/利空/中性
def analyze(title):
    t = title.lower()

    # ===== 明确利空（SELL）=====
    sell_kw = [
        ("终止", "项目终止/产能收缩"),
        ("跌停", "股价跌停"),
        ("减持", "股东减持"),
        ("诉讼", "诉讼风险"),
        ("处罚", "监管处罚"),
        ("被查", "遭调查"),
        ("调查", "遭调查"),
        ("净流出", "主力资金净流出"),
        ("流出", "资金流出"),
        ("走弱", "板块走弱"),
        ("下跌", "概念下跌"),
        ("跳水", "股价跳水"),
        ("死叉", "技术面死叉"),
        ("减仓", "杠杆资金减仓"),
        ("连降", "融资余额连降"),
        ("出逃", "主力资金出逃"),
        ("巨震", "股价巨震/复牌巨震"),
        ("大跌", "股价大跌"),
        ("亏", "亏损"),
    ]
    # 利空需谨慎：有些"下跌/流出"是板块整体描述，与公司自身无直接利空
    # 区分：若标题同时含明显个股利空动作词，则判 SELL

    # ===== 明确利好（BUY）=====
    buy_kw = [
        ("净利预增", "业绩预增"),
        ("净利润同比预增", "业绩预增"),
        ("净利润预增", "业绩预增"),
        ("净利预盈", "业绩预盈"),
        ("扭亏为盈", "扭亏为盈"),
        ("预增", "业绩预增"),
        ("回购", "股份回购"),
        ("分红", "分红派息"),
        ("签下", "大额订单"),
        ("订单", "获新订单"),
        ("增资", "增资扩产"),
        ("扩产", "扩产"),
        ("涨停", "股价涨停/强势"),
        ("大涨", "股价大涨"),
        ("飘红", "板块走强"),
        ("净流入", "主力资金净流入"),
        ("机构买入", "机构买入评级"),
        ("买入评级", "机构买入评级"),
        ("中标", "中标"),
        ("历史新高", "股价创历史新高"),
        ("爆发", "板块爆发"),
        ("反弹", "板块反弹"),
        ("走强", "板块走强"),
        ("净流入资金超亿元", "资金净流入"),
        ("净买入超亿元", "融资净买入"),
        ("净买入居前", "融资净买入"),
        ("快速拉升", "股价异动拉升"),
        ("抢筹", "资金抢筹"),
    ]

    # 利空优先精确匹配（带明确负面动作）
    strong_sell = {
        "终止": "项目终止/产能收缩利空",
        "跌停": "股价跌停利空",
        "减持": "股东减持利空",
        "诉讼": "诉讼风险利空",
        "处罚": "监管处罚利空",
        "被查": "遭调查利空",
        "调查": "遭调查利空",
        "跳水": "股价跳水利空",
        "死叉": "技术面死叉利空",
        "出逃": "主力资金出逃利空",
        "大跌": "股价大跌利空",
        "巨震": "股价巨震波动利空",
        "亏": "亏损利空",
    }
    for k, reason in strong_sell.items():
        if k in title:
            return "SELL", 0.7, reason

    # 业绩亏损类
    if "亏损" in title and "扭亏" not in title:
        return "SELL", 0.7, "业绩亏损利空"

    # 板块整体下跌/流出但非个股动作 → 中性（除非明确点名个股弱势）
    # 利好匹配
    for k, reason in buy_kw:
        if k in title:
            # 避免把"下跌"误判；buy_kw不含下跌
            return "BUY", 0.75, "利好：" + reason

    # 资金净流出/流出/减仓/连降 → 个股层面利空或中性
    if any(x in title for x in ["净流出", "流出资金", "减仓", "连降", "走弱", "下跌"]):
        # 板块整体描述（含"概念""行业""板块"且未点名具体个股利空动作）视为中性
        if any(seg in title for seg in ["概念", "行业", "板块", "股"]):
            return "HOLD", 0.4, "中性：板块资金流向描述，非个股直接利空"
        return "SELL", 0.55, "利空：资金流出"

    # 龙虎榜数据（中性，仅数据披露）
    if "龙虎榜数据" in title:
        return "HOLD", 0.3, "中性：龙虎榜数据披露，无明确方向"

    # 机构调研/调研名单
    if "调研" in title:
        return "HOLD", 0.4, "中性：机构调研，信息不明确"

    # 大宗交易
    if "大宗交易" in title:
        return "HOLD", 0.35, "中性：大宗交易披露，方向不明"

    # 兜底中性
    return "HOLD", 0.3, "中性：信息不明确"


def main():
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)
    signals = data["signals"]

    conn = sqlite3.connect(DB)
    c = conn.cursor()

    counts = {"BUY": 0, "SELL": 0, "HOLD": 0}
    rows = []
    for s in signals:
        action, conf, reason = analyze(s["title"])
        rows.append((action, conf, reason, s["id"]))
        counts[action] += 1

    c.executemany(
        "UPDATE strategy_shadow_signals SET signal_action=?, confidence=?, signal_reason=? WHERE id=?",
        rows,
    )
    conn.commit()
    conn.close()
    print("更新完成，总计:", len(rows))
    print("BUY:", counts["BUY"], "SELL:", counts["SELL"], "HOLD:", counts["HOLD"])
    # 输出汇总供推送
    print("SUMMARY|%d|%d|%d" % (counts["BUY"], counts["SELL"], counts["HOLD"]))

if __name__ == "__main__":
    main()
