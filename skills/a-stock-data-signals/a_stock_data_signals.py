"""
a_stock_data_signals.py — a-stock-data 数据源集成模块

将 a-stock-data SKILL 中的 27 个数据端点封装为策略可用的信号函数。
设计原则：
  - 每个函数返回纯数据（dict / list / DataFrame），不依赖我们的策略引擎
  - 东财接口统一走 em_get() 限流
  - 优先用 mootdx / 腾讯（不封 IP），东财仅用于独有数据

使用方式：
  from skills.a_stock_data_signals.a_stock_data_signals import (
      hot_stocks_signal,          # 当日强势股 + 题材归因
      northbound_signal,          # 北向资金分钟级流向
      dragon_tiger_signal,        # 龙虎榜席位
      daily_dragon_tiger_signal,  # 全市场龙虎榜
      lockup_warning_signal,      # 解禁预警
      industry_rotation_signal,   # 行业轮动
      concept_blocks_signal,      # 个股概念板块归属
      fund_flow_signal,           # 个股资金流向
      margin_trading_signal,      # 融资融券
      block_trade_signal,         # 大宗交易
      shareholder_count_signal,   # 股东户数变化
      multi_signal_report,        # 多信号综合报告
  )
"""

import time
import random
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import pandas as pd

# ── 东财防封：全局节流 + 会话复用 ────────────────────────────────────
EM_SESSION = requests.Session()
EM_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
})
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
PUSH2_URL = "https://push2.eastmoney.com/api/qt/slist/get"
PUSH2_FFLOW_URL = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
HSGT_URL = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
THS_HOT_URL = "http://zx.10jqka.com.cn/event/api/getharden/"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def em_get(url: str, params: dict | None = None, headers: dict | None = None,
           timeout: int = 15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                          filter_str: str = "", page_size: int = 50,
                          sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    """东财数据中心统一查询（已内置限流）"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ═══════════════════════════════════════════════════════════════════
# 信号 1: 当日强势股 + 题材归因 (同花顺热点)
# ═══════════════════════════════════════════════════════════════════

def hot_stocks_signal(date: str = None, top_n: int = 30) -> dict:
    """
    当日强势股 + 题材归因 reason tags。
    返回: {date, total, stocks: [{code, name, change_pct, reason, ...}], top_tags: [...]}
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    url = f"{THS_HOT_URL}date/{date}/orderby/date/orderway/desc/charset/GBK/"
    headers = {"User-Agent": UA}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
    except Exception as e:
        return {"date": date, "total": 0, "stocks": [], "top_tags": [], "error": str(e)}

    if data.get("errocode", 0) != 0:
        return {"date": date, "total": 0, "stocks": [], "top_tags": [],
                "error": data.get("errormsg", "")}

    rows = data.get("data") or []
    stocks = []
    for row in rows[:top_n]:
        stocks.append({
            "code": row.get("code", ""),
            "name": row.get("name", ""),
            "close": row.get("close", 0),
            "change_pct": round(float(row.get("zhangfu") or 0), 2),
            "change_amt": round(float(row.get("zhangdie") or 0), 2),
            "turnover_pct": round(float(row.get("huanshou") or 0), 2),
            "amount": row.get("chengjiaoe", 0),
            "reason": row.get("reason", ""),
        })

    # 题材词频统计
    from collections import Counter
    all_tags = []
    for s in stocks:
        if s["reason"]:
            tags = [t.strip() for t in str(s["reason"]).split("+") if t.strip()]
            all_tags.extend(tags)
    top_tags = [{"tag": t, "count": n} for t, n in Counter(all_tags).most_common(15)]

    return {
        "date": date,
        "total": len(stocks),
        "stocks": stocks,
        "top_tags": top_tags,
    }


# ═══════════════════════════════════════════════════════════════════
# 信号 2: 北向资金分钟级流向 (同花顺 hsgtApi)
# ═══════════════════════════════════════════════════════════════════

def northbound_signal() -> dict:
    """
    北向资金实时分钟级流向。
    返回: {date, hgt_total, sgt_total, hgt_sgt_total, direction, data_points}
    """
    headers = {
        "User-Agent": UA,
        "Host": "data.hexin.cn",
        "Referer": "https://data.hexin.cn/",
    }
    try:
        r = requests.get(HSGT_URL, headers=headers, timeout=10)
        d = r.json()
    except Exception as e:
        return {"error": str(e), "date": datetime.now().strftime("%Y-%m-%d")}

    times = d.get("time", [])
    hgt = d.get("hgt", [])
    sgt = d.get("sgt", [])

    if not times:
        return {"date": datetime.now().strftime("%Y-%m-%d"), "data_points": 0}

    hgt_last = float(hgt[-1]) if hgt else 0
    sgt_last = float(sgt[-1]) if sgt else 0
    total = hgt_last + sgt_last

    if total > 50:
        direction = "大幅流入"
    elif total > 10:
        direction = "温和流入"
    elif total > -10:
        direction = "小幅波动"
    elif total > -50:
        direction = "温和流出"
    else:
        direction = "大幅流出"

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "hgt_total": round(hgt_last, 2),
        "sgt_total": round(sgt_last, 2),
        "hgt_sgt_total": round(total, 2),
        "direction": direction,
        "data_points": len(times),
        "latest_minutes": [
            {"time": times[i], "hgt": hgt[i], "sgt": sgt[i]}
            for i in range(max(0, len(times) - 5), len(times))
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# 信号 3: 龙虎榜席位 (个股)
# ═══════════════════════════════════════════════════════════════════

def dragon_tiger_signal(code: str, trade_date: str = None, look_back: int = 30) -> dict:
    """
    个股龙虎榜席位分析。
    返回: {code, name, records: [...], seats: {buy, sell}, institution: {...}}
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    start = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)
    start_str = start.strftime("%Y-%m-%d")

    # 1. 上榜记录
    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start_str}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")",
        page_size=50,
        sort_columns="TRADE_DATE", sort_types="-1",
    )
    for row in data:
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
            "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
            "close": row.get("CLOSE_PRICE") or 0,
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
        })

    # 2. 买卖席位
    seats = {"buy": [], "sell": []}
    if records:
        latest_date = records[0]["date"]
        for side, report in [("buy", "RPT_BILLBOARD_DAILYDETAILSBUY"), ("sell", "RPT_BILLBOARD_DAILYDETAILSSELL")]:
            sd = eastmoney_datacenter(
                report,
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10,
                sort_columns="BUY" if side == "buy" else "SELL", sort_types="-1",
            )
            for row in sd[:5]:
                seats[side].append({
                    "name": row.get("OPERATEDEPT_NAME", ""),
                    "buy_amt": round((row.get("BUY") or 0) / 10000, 1),
                    "sell_amt": round((row.get("SELL") or 0) / 10000, 1),
                    "net": round((row.get("NET") or 0) / 10000, 1),
                })

    # 3. 机构统计
    institution = {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}
    for side, report in [("buy", "RPT_BILLBOARD_DAILYDETAILSBUY"), ("sell", "RPT_BILLBOARD_DAILYDETAILSSELL")]:
        sd = eastmoney_datacenter(
            report,
            filter_str=f"(TRADE_DATE='{records[0]['date']}')(SECURITY_CODE=\"{code}\")",
            page_size=50,
        )
        for row in sd:
            if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                amt = (row.get("BUY") or 0)
                if side == "buy":
                    institution["buy_amt"] += amt
                else:
                    institution["sell_amt"] += amt
    institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
    institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
    institution["net_amt"] = round(institution["buy_amt"] - institution["sell_amt"], 1)

    return {
        "code": code,
        "records": records,
        "seats": seats,
        "institution": institution,
    }


# ═══════════════════════════════════════════════════════════════════
# 信号 4: 全市场龙虎榜
# ═══════════════════════════════════════════════════════════════════

def daily_dragon_tiger_signal(trade_date: str = None, min_net_buy_wan: float = None) -> dict:
    """
    全市场龙虎榜汇总。
    返回: {date, total, stocks: [{code, name, reason, net_buy_wan, ...}]}
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
        page_size=500,
        sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    if not data:
        return {"date": trade_date, "total": 0, "stocks": [], "note": "无数据（非交易日或盘后未更新）"}

    actual_date = str(data[0].get("TRADE_DATE", ""))[:10]
    stocks = []
    for row in data:
        net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
        if min_net_buy_wan is not None and net_buy < min_net_buy_wan:
            continue
        stocks.append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "reason": row.get("EXPLANATION", ""),
            "close": row.get("CLOSE_PRICE") or 0,
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
            "net_buy_wan": round(net_buy, 1),
            "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
            "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
        })
    return {"date": actual_date, "total": len(stocks), "stocks": stocks}


# ═══════════════════════════════════════════════════════════════════
# 信号 5: 限售解禁预警
# ═══════════════════════════════════════════════════════════════════

def lockup_warning_signal(code: str, trade_date: str = None, forward_days: int = 90) -> dict:
    """
    个股限售解禁预警。
    返回: {code, history: [...], upcoming: [...], has_upcoming, total_upcoming_shares}
    """
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    end_date = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)
    end_str = end_date.strftime("%Y-%m-%d")

    # 未来待解禁
    upcoming_data = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f"(SECURITY_CODE=\"{code}\")(FREE_DATE>='{trade_date}')(FREE_DATE<='{end_str}')",
        page_size=20,
        sort_columns="FREE_DATE", sort_types="1",
    )
    upcoming = []
    for row in upcoming_data:
        upcoming.append({
            "date": str(row.get("FREE_DATE", ""))[:10],
            "type": row.get("LIMITED_STOCK_TYPE", ""),
            "shares": row.get("FREE_SHARES_NUM", 0),
            "ratio": row.get("FREE_RATIO", 0),
        })

    # 历史解禁
    history_data = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f"(SECURITY_CODE=\"{code}\")",
        page_size=15,
        sort_columns="FREE_DATE", sort_types="-1",
    )
    history = []
    for row in history_data:
        history.append({
            "date": str(row.get("FREE_DATE", ""))[:10],
            "type": row.get("LIMITED_STOCK_TYPE", ""),
            "shares": row.get("FREE_SHARES_NUM", 0),
            "ratio": row.get("FREE_RATIO", 0),
        })

    total_shares = sum(u.get("shares", 0) or 0 for u in upcoming)
    return {
        "code": code,
        "history": history,
        "upcoming": upcoming,
        "has_upcoming": len(upcoming) > 0,
        "total_upcoming_shares": total_shares,
    }


# ═══════════════════════════════════════════════════════════════════
# 信号 6: 行业轮动
# ═══════════════════════════════════════════════════════════════════

def industry_rotation_signal(top_n: int = 20) -> dict:
    """
    行业轮动信号（基于同花顺热点题材 + 腾讯指数）。
    不依赖东财 push2（该接口间歇风控）。
    返回: {hot_sectors: [...], top_industries: [...], total}
    """
    # 方式1: 从同花顺热点提取题材热度
    try:
        hs = hot_stocks_signal(top_n=50)
        top_tags = hs.get("top_tags", [])
        hot_sectors = [t["tag"] for t in top_tags[:top_n]]
    except Exception as e:
        hot_sectors = []

    # 方式2: 用腾讯财经拉主要指数涨跌幅
    try:
        index_codes = ["000001", "399001", "399006", "000016", "000300", "000688", "399852"]
        prefixed = []
        for c in index_codes:
            if c.startswith(("6", "9")):
                prefixed.append(f"sh{c}")
            else:
                prefixed.append(f"sz{c}")
        url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
        req = requests.Request("GET", url, headers={"User-Agent": UA})
        resp = requests.Session().send(req.prepare(), timeout=10)
        data = resp.content.decode("gbk")

        index_map = {
            "000001": "上证指数", "399001": "深证成指", "399006": "创业板指",
            "000016": "上证50", "000300": "沪深300", "000688": "科创50",
            "399852": "中证1000",
        }
        indices = []
        for line in data.strip().split(";"):
            if not line.strip() or "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            vals = line.split('"')[1].split("~")
            if len(vals) < 33:
                continue
            code = key[2:]
            if code in index_map:
                indices.append({
                    "name": index_map[code],
                    "code": code,
                    "price": float(vals[3]) if vals[3] else 0,
                    "change_pct": float(vals[32]) if vals[32] else 0,
                })
    except Exception as e:
        indices = []

    return {
        "hot_sectors": hot_sectors,
        "indices": indices,
        "total": len(hot_sectors),
    }


# ═══════════════════════════════════════════════════════════════════
# 信号 7: 个股概念板块归属
# ═══════════════════════════════════════════════════════════════════

def concept_blocks_signal(code: str) -> dict:
    """
    个股所属板块/概念归属。
    返回: {code, total, boards: [{name, code, change_pct, lead_stock}], concept_tags: [...]}
    """
    market_code = 1 if code.startswith("6") else 0
    params = {
        "fltt": "2", "invt": "2",
        "secid": f"{market_code}.{code}",
        "spt": "3", "pi": "0", "pz": "200", "po": "1",
        "fields": "f12,f14,f3,f128",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get("https://push2.eastmoney.com/api/qt/slist/get",
                   params=params, headers=headers, timeout=15)
        d = r.json()
    except Exception as e:
        return {"code": code, "total": 0, "boards": [], "concept_tags": [], "error": str(e)}

    diff = (d.get("data") or {}).get("diff") or {}
    items = diff.values() if isinstance(diff, dict) else diff
    boards = []
    for it in items:
        boards.append({
            "name": it.get("f14", ""),
            "code": it.get("f12", ""),
            "change_pct": it.get("f3", ""),
            "lead_stock": it.get("f128", ""),
        })
    return {
        "code": code,
        "total": len(boards),
        "boards": boards,
        "concept_tags": [b["name"] for b in boards],
    }


# ═══════════════════════════════════════════════════════════════════
# 信号 8: 个股资金流向（分钟级）
# ═══════════════════════════════════════════════════════════════════

def fund_flow_signal(code: str) -> dict:
    """
    个股资金流向（分钟级，当日盘中）。
    返回: {code, total_minutes, main_net_total, direction, details: [...]}
    """
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    params = {
        "secid": secid, "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/",
               "Origin": "https://quote.eastmoney.com"}
    try:
        r = em_get(PUSH2_FFLOW_URL, params=params, headers=headers, timeout=10)
        d = r.json()
    except Exception as e:
        return {"code": code, "error": str(e)}

    klines = d.get("data", {}).get("klines", [])
    details = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 6:
            details.append({
                "time": parts[0],
                "main_net": float(parts[1]),
                "small_net": float(parts[2]),
                "mid_net": float(parts[3]),
                "large_net": float(parts[4]),
                "super_net": float(parts[5]),
            })

    if not details:
        return {"code": code, "total_minutes": 0, "main_net_total": 0, "direction": "无数据"}

    main_total = sum(d["main_net"] for d in details)
    if main_total > 10000000:
        direction = "主力大幅流入"
    elif main_total > 0:
        direction = "主力流入"
    elif main_total > -10000000:
        direction = "主力流出"
    else:
        direction = "主力大幅流出"

    return {
        "code": code,
        "total_minutes": len(details),
        "main_net_total": round(main_total, 2),
        "main_net_total_wan": round(main_total / 10000, 2),
        "direction": direction,
        "last_5": details[-5:] if len(details) >= 5 else details,
    }


# ═══════════════════════════════════════════════════════════════════
# 信号 9: 融资融券
# ═══════════════════════════════════════════════════════════════════

def margin_trading_signal(code: str, page_size: int = 30) -> dict:
    """
    融资融券明细。
    返回: {code, records: [{date, rzye, rzmre, rqye, ...}], trend}
    """
    data = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX",
        filter_str=f'(SCODE="{code}")',
        page_size=page_size,
        sort_columns="DATE", sort_types="-1",
    )
    records = []
    for row in data:
        records.append({
            "date": str(row.get("DATE", ""))[:10],
            "rzye": row.get("RZYE", 0),
            "rzmre": row.get("RZMRE", 0),
            "rzche": row.get("RZCHE", 0),
            "rqye": row.get("RQYE", 0),
            "rzrqye": row.get("RZRQYE", 0),
        })

    # 趋势判断
    trend = "未知"
    if len(records) >= 5:
        recent_avg = sum(r["rzmre"] or 0 for r in records[:5]) / 5
        older_avg = sum(r["rzmre"] or 0 for r in records[-5:]) / 5
        if recent_avg > older_avg * 1.2:
            trend = "融资买入增加（看多情绪）"
        elif recent_avg < older_avg * 0.8:
            trend = "融资买入减少（看多情绪减弱）"
        else:
            trend = "融资平稳"

    return {"code": code, "records": records, "trend": trend}


# ═══════════════════════════════════════════════════════════════════
# 信号 10: 大宗交易
# ═══════════════════════════════════════════════════════════════════

def block_trade_signal(code: str, page_size: int = 20) -> dict:
    """
    大宗交易记录。
    返回: {code, records: [{date, price, premium_pct, buyer, seller, ...}]}
    """
    data = eastmoney_datacenter(
        "RPT_DATA_BLOCKTRADE",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size,
        sort_columns="TRADE_DATE", sort_types="-1",
    )
    records = []
    for row in data:
        close = row.get("CLOSE_PRICE") or 0
        deal_price = row.get("DEAL_PRICE") or 0
        premium = ((deal_price / close - 1) * 100) if close else 0
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "price": deal_price,
            "close": close,
            "premium_pct": round(premium, 2),
            "vol": row.get("DEAL_VOLUME", 0),
            "amount": row.get("DEAL_AMT", 0),
            "buyer": row.get("BUYER_NAME", ""),
            "seller": row.get("SELLER_NAME", ""),
        })
    return {"code": code, "records": records}


# ═══════════════════════════════════════════════════════════════════
# 信号 11: 股东户数变化（筹码集中度）
# ═══════════════════════════════════════════════════════════════════

def shareholder_count_signal(code: str, page_size: int = 10) -> dict:
    """
    股东户数变化（筹码集中度）。
    返回: {code, records: [{date, holders, change_pct, avg_shares}], trend}
    """
    data = eastmoney_datacenter(
        "RPT_HOLDERNUMLATEST",
        filter_str=f'(SECURITY_CODE="{code}")',
        page_size=page_size,
        sort_columns="END_DATE", sort_types="-1",
    )
    records = []
    for row in data:
        records.append({
            "date": str(row.get("END_DATE", ""))[:10],
            "holders": row.get("HOLDER_NUM", 0),
            "change_pct": round(float(row.get("CHANGE_NUM") or 0), 2),
            "avg_shares": row.get("AVG_MARKET_CAP", 0),
        })

    trend = "未知"
    if len(records) >= 2:
        if records[0]["change_pct"] < -5:
            trend = "筹码集中（股东户数减少）"
        elif records[0]["change_pct"] > 5:
            trend = "筹码分散（股东户数增加）"
        else:
            trend = "筹码稳定"

    return {"code": code, "records": records, "trend": trend}


# ═══════════════════════════════════════════════════════════════════
# 综合信号报告（多信号聚合）
# ═══════════════════════════════════════════════════════════════════

def multi_signal_report(codes: list[str] = None) -> dict:
    """
    多信号综合报告。
    聚合：强势股题材、北向资金、全市场龙虎榜、行业轮动。
    如果提供 codes，额外拉取每只个股的龙虎榜、解禁、资金流向、概念板块。
    """
    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    # 1. 强势股题材
    try:
        report["hot_stocks"] = hot_stocks_signal(top_n=30)
    except Exception as e:
        report["hot_stocks"] = {"error": str(e)}

    # 2. 北向资金
    try:
        report["northbound"] = northbound_signal()
    except Exception as e:
        report["northbound"] = {"error": str(e)}

    # 3. 全市场龙虎榜
    try:
        report["dragon_tiger"] = daily_dragon_tiger_signal(min_net_buy_wan=3000)
    except Exception as e:
        report["dragon_tiger"] = {"error": str(e)}

    # 4. 行业轮动
    try:
        report["industry"] = industry_rotation_signal(top_n=10)
    except Exception as e:
        report["industry"] = {"error": str(e)}

    # 5. 个股级信号（如果提供了 codes）
    if codes:
        stock_signals = {}
        for code in codes:
            stock = {}
            try:
                stock["concept_blocks"] = concept_blocks_signal(code)
            except Exception as e:
                stock["concept_blocks"] = {"error": str(e)}
            try:
                stock["lockup"] = lockup_warning_signal(code)
            except Exception as e:
                stock["lockup"] = {"error": str(e)}
            try:
                stock["fund_flow"] = fund_flow_signal(code)
            except Exception as e:
                stock["fund_flow"] = {"error": str(e)}
            try:
                stock["dragon_tiger"] = dragon_tiger_signal(code)
            except Exception as e:
                stock["dragon_tiger"] = {"error": str(e)}
            try:
                stock["margin"] = margin_trading_signal(code)
            except Exception as e:
                stock["margin"] = {"error": str(e)}
            try:
                stock["block_trade"] = block_trade_signal(code)
            except Exception as e:
                stock["block_trade"] = {"error": str(e)}
            try:
                stock["shareholders"] = shareholder_count_signal(code)
            except Exception as e:
                stock["shareholders"] = {"error": str(e)}
            stock_signals[code] = stock
        report["stocks"] = stock_signals

    return report


# ═══════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json

    print("=" * 60)
    print("a-stock-data 信号集成模块 — 综合报告")
    print("=" * 60)

    report = multi_signal_report()

    # 强势股
    hs = report.get("hot_stocks", {})
    print(f"\n📊 当日强势股: {hs.get('total', 0)} 只")
    print(f"   题材热度 TOP5: {', '.join(t['tag'] for t in hs.get('top_tags', [])[:5])}")

    # 北向
    nb = report.get("northbound", {})
    print(f"\n💰 北向资金: {nb.get('direction', 'N/A')} (沪{nb.get('hgt_total', 0)}亿 + 深{nb.get('sgt_total', 0)}亿 = {nb.get('hgt_sgt_total', 0)}亿)")

    # 龙虎榜
    dt = report.get("dragon_tiger", {})
    print(f"\n🐉 龙虎榜 (净买>3000万): {dt.get('total', 0)} 只")
    for s in dt.get("stocks", [])[:5]:
        print(f"   {s['code']} {s['name']}: 净买{s['net_buy_wan']}万 | {s['reason']}")

    # 行业
    ind = report.get("industry", {})
    print(f"\n🏭 行业涨幅 TOP5:")
    for r in ind.get("top", [])[:5]:
        print(f"   {r['name']}: {r['change_pct']}% 领涨{r['leader']}")

    print("\n✅ 报告完成")


# ═══════════════════════════════════════════════════════════════════
# 腾讯财经实时行情（watchlist_deep_scan 需要）
# ═══════════════════════════════════════════════════════════════════

def tencent_quote(codes: list[str]) -> dict[str, dict]:
    """
    批量拉取腾讯财经实时行情。
    codes: ["688017", "300476", "002463"]
    返回: {code: {name, price, pe_ttm, pb, mcap, ...}}
    """
    import urllib.request

    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
    except Exception as e:
        return {}

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name":         vals[1],
            "price":        float(vals[3]) if vals[3] else 0,
            "last_close":   float(vals[4]) if vals[4] else 0,
            "open":         float(vals[5]) if vals[5] else 0,
            "change_amt":   float(vals[31]) if vals[31] else 0,
            "change_pct":   float(vals[32]) if vals[32] else 0,
            "high":         float(vals[33]) if vals[33] else 0,
            "low":          float(vals[34]) if vals[34] else 0,
            "amount_wan":   float(vals[37]) if vals[37] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm":       float(vals[39]) if vals[39] else 0,
            "amplitude_pct":float(vals[43]) if vals[43] else 0,
            "mcap_yi":      float(vals[44]) if vals[44] else 0,
            "float_mcap_yi":float(vals[45]) if vals[45] else 0,
            "pb":           float(vals[46]) if vals[46] else 0,
            "limit_up":     float(vals[47]) if vals[47] else 0,
            "limit_down":   float(vals[48]) if vals[48] else 0,
            "vol_ratio":    float(vals[49]) if vals[49] else 0,
            "pe_static":    float(vals[52]) if vals[52] else 0,
        }
    return result
