#!/usr/bin/env python3
"""
scripts/portfolio_analyze.py — 实盘持仓分析（不靠 QMT）

输入：你当前的持仓（手动填，或从 portfolio.json 读）
输出：每只股票
  - 多策略综合信号（5 个策略投票）
  - 当前盈亏 + 距离止损/止盈位
  - BUY / SELL / HOLD 决策 + 理由
  - 仓位建议
"""

import os
import sys
import json
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_DIR, "data")

# 你的持仓（来自截图 02:17）
PORTFOLIO = [
    {"code": "002256", "name": "兆新股份", "qty": 700, "cost": 5.246,  "current": 4.850},
    {"code": "000967", "name": "盈峰环境", "qty": 400, "cost": 12.660, "current": 14.250},
    {"code": "002453", "name": "华软科技", "qty": 300, "cost": 6.467,  "current": 6.380},
    {"code": "600330", "name": "天通股份", "qty": 300, "cost": 33.774, "current": 32.800},
]
TOTAL_ASSETS = 22158.37
CASH = 1309.37


# ---------- 5 个策略的"今日信号"判断 ----------
def load_klines(code):
    p = os.path.join(DATA_DIR, f"{code}.csv")
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p, parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)


def add_indicators(df):
    """补常用指标"""
    df = df.copy()
    df["ma5"]  = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["dif"]  = ema12 - ema26
    df["dea"]  = df["dif"].ewm(span=9, adjust=False).mean()
    df["macd"] = (df["dif"] - df["dea"]) * 2

    # 布林
    df["boll_mid"]   = df["close"].rolling(20).mean()
    std              = df["close"].rolling(20).std()
    df["boll_upper"] = df["boll_mid"] + 2 * std
    df["boll_lower"] = df["boll_mid"] - 2 * std

    # RSI(14)
    diff = df["close"].diff()
    up   = diff.clip(lower=0).rolling(14).mean()
    down = (-diff.clip(upper=0)).rolling(14).mean()
    rs = up / down.replace(0, 1e-9)
    df["rsi"] = 100 - 100 / (1 + rs)

    # 20 日波动率
    df["vol20"] = df["close"].pct_change().rolling(20).std() * (252 ** 0.5)

    return df


def signal_sma(df):
    """双均线：MA5 上穿 MA10 BUY，下穿 SELL"""
    if len(df) < 11: return ("HOLD", "数据不足")
    p = df.iloc[-2]; n = df.iloc[-1]
    if p["ma5"] <= p["ma10"] and n["ma5"] > n["ma10"]:
        return ("BUY", f"MA5({n['ma5']:.2f})上穿MA10({n['ma10']:.2f})")
    if p["ma5"] >= p["ma10"] and n["ma5"] < n["ma10"]:
        return ("SELL", f"MA5({n['ma5']:.2f})下穿MA10({n['ma10']:.2f})")
    if n["ma5"] > n["ma10"]:
        return ("HOLD", f"短均线在长均线上方（多头）")
    return ("HOLD", f"短均线在长均线下方（空头）")


def signal_macd(df):
    """MACD：DIF 上穿 DEA + MACD>0 BUY"""
    if len(df) < 30: return ("HOLD", "数据不足")
    p = df.iloc[-2]; n = df.iloc[-1]
    if p["dif"] <= p["dea"] and n["dif"] > n["dea"]:
        return ("BUY", f"MACD金叉(DIF={n['dif']:.3f})")
    if p["dif"] >= p["dea"] and n["dif"] < n["dea"]:
        return ("SELL", f"MACD死叉(DIF={n['dif']:.3f})")
    if n["dif"] > n["dea"] and n["macd"] > 0:
        return ("HOLD", "MACD多头未变")
    return ("HOLD", "MACD空头未变")


def signal_bollinger(df):
    """布林：跌破下轨 BUY，突破上轨 SELL"""
    if len(df) < 21: return ("HOLD", "数据不足")
    n = df.iloc[-1]
    if n["close"] < n["boll_lower"]:
        return ("BUY", f"跌破布林下轨({n['boll_lower']:.2f})可能反弹")
    if n["close"] > n["boll_upper"]:
        return ("SELL", f"突破布林上轨({n['boll_upper']:.2f})可能回调")
    pos = (n["close"] - n["boll_lower"]) / max(n["boll_upper"] - n["boll_lower"], 1e-6)
    return ("HOLD", f"布林通道内（{pos*100:.0f}%位）")


def signal_composite(df):
    """复合：MA10 + MACD + RSI 综合"""
    if len(df) < 30: return ("HOLD", "数据不足")
    n = df.iloc[-1]; p = df.iloc[-2]
    buy_score = 0; sell_score = 0; reasons = []

    if n["close"] > n["ma10"]: buy_score += 1; reasons.append("收盘>MA10")
    else:                       sell_score += 1; reasons.append("收盘<MA10")
    if n["dif"] > n["dea"]:     buy_score += 1; reasons.append("MACD多头")
    else:                       sell_score += 1; reasons.append("MACD空头")
    if 30 < n["rsi"] < 70:      buy_score += 1; reasons.append(f"RSI正常({n['rsi']:.0f})")
    elif n["rsi"] >= 70:        sell_score += 1; reasons.append(f"RSI超买({n['rsi']:.0f})")
    else:                        buy_score += 1; reasons.append(f"RSI超卖({n['rsi']:.0f})")

    if buy_score >= 2 and sell_score == 0:
        return ("BUY", "+".join(reasons))
    if sell_score >= 2 and buy_score == 0:
        return ("SELL", "+".join(reasons))
    return ("HOLD", "+".join(reasons))


def signal_composite_v2(df):
    """复合 V2：考虑趋势强度，要求多重确认"""
    if len(df) < 60: return ("HOLD", "数据不足")
    n = df.iloc[-1]; reasons = []

    # 大趋势（MA60）
    trend_up = n["close"] > n["ma60"]
    reasons.append(f"{'多头' if trend_up else '空头'}趋势(MA60)")

    if trend_up:
        # 多头趋势中只找买点
        if n["close"] > n["ma20"] and n["dif"] > n["dea"] and n["rsi"] < 70:
            return ("BUY", "+".join(reasons + ["20日上穿", "MACD多", "RSI未超买"]))
        if n["close"] < n["ma10"] and n["rsi"] > 70:
            return ("SELL", "+".join(reasons + ["跌破MA10", "RSI超买"]))
    else:
        # 空头趋势：保守，只看止损
        if n["close"] < n["ma10"]:
            return ("SELL", "+".join(reasons + ["跌破MA10"]))

    return ("HOLD", "+".join(reasons + ["等更明确信号"]))


STRATEGIES = {
    "双均线": signal_sma,
    "MACD":   signal_macd,
    "布林带": signal_bollinger,
    "复合":   signal_composite,
    "复合V2": signal_composite_v2,
}


# ---------- 决策融合 ----------
def vote(signals):
    """5 个策略投票 + 按 PK 结果加权"""
    # 来自 strategy_pk_summary 的"可信度"权重
    weight = {"双均线": 0.5, "MACD": 1.5, "布林带": 0.3, "复合": 1.8, "复合V2": 1.0}
    score = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    for name, (sig, _) in signals.items():
        score[sig] += weight.get(name, 1.0)

    total = sum(score.values())
    pct = {k: v / total * 100 for k, v in score.items()}

    # 决策：占优 50% 以上才"动"，否则 HOLD
    sorted_sig = sorted(score.items(), key=lambda x: -x[1])
    top_sig, top_score = sorted_sig[0]
    confidence = pct[top_sig]
    if top_sig == "HOLD" or confidence < 50:
        return "HOLD", confidence, pct
    return top_sig, confidence, pct


def analyze_position(stock):
    """单只股票分析"""
    df = load_klines(stock["code"])
    if df is None:
        return {"error": f"没有 {stock['code']} 的历史数据"}
    df = add_indicators(df)

    signals = {name: fn(df) for name, fn in STRATEGIES.items()}
    decision, confidence, pct = vote(signals)

    # 当前指标快照
    n = df.iloc[-1]
    last_close = float(n["close"])
    last_date = n["date"].strftime("%Y-%m-%d") if hasattr(n["date"], "strftime") else str(n["date"])[:10]

    cost = stock["cost"]
    current = stock["current"]
    qty = stock["qty"]
    market_value = qty * current
    pnl = (current - cost) * qty
    pnl_pct = (current / cost - 1) * 100

    # 止损/止盈位（基于成本）
    stop_loss_8 = cost * 0.92
    stop_loss_10 = cost * 0.90
    take_profit_15 = cost * 1.15
    take_profit_20 = cost * 1.20

    return {
        "code": stock["code"],
        "name": stock["name"],
        "qty": qty,
        "cost": cost,
        "current": current,
        "last_close_in_data": last_close,
        "last_data_date": last_date,
        "market_value": market_value,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "ma5": float(n["ma5"]),
        "ma10": float(n["ma10"]),
        "ma20": float(n["ma20"]),
        "ma60": float(n["ma60"]),
        "rsi": float(n["rsi"]),
        "macd_dif": float(n["dif"]),
        "macd_dea": float(n["dea"]),
        "boll_pos": (last_close - float(n["boll_lower"])) / max(float(n["boll_upper"]) - float(n["boll_lower"]), 1e-6),
        "vol20": float(n["vol20"]) * 100,
        "signals": signals,
        "decision": decision,
        "confidence": confidence,
        "vote_pct": pct,
        "stop_loss_8": stop_loss_8,
        "stop_loss_10": stop_loss_10,
        "take_profit_15": take_profit_15,
        "take_profit_20": take_profit_20,
    }


# ---------- 输出 ----------
def emoji(decision):
    return {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(decision, "❓")


def print_report(results):
    total_market = sum(r["market_value"] for r in results if "error" not in r)
    total_pnl = sum(r["pnl"] for r in results if "error" not in r)

    print("=" * 80)
    print(f"{'📊 持仓综合分析报告':^80}")
    print(f"{'生成时间: ' + datetime.now().strftime('%Y-%m-%d %H:%M'):^80}")
    print("=" * 80)
    print(f"总资产: ¥{TOTAL_ASSETS:,.2f}  |  持仓市值: ¥{total_market:,.2f}  |  "
          f"现金: ¥{CASH:,.2f}  |  仓位: {total_market/TOTAL_ASSETS*100:.1f}%")
    print(f"持仓盈亏: ¥{total_pnl:+,.2f} ({total_pnl/(total_market-total_pnl)*100:+.2f}%)")
    print("=" * 80)

    for r in results:
        if "error" in r:
            print(f"\n❌ {r['error']}")
            continue

        print(f"\n{emoji(r['decision'])} 【{r['decision']}】 {r['name']}({r['code']})  "
              f"信心度 {r['confidence']:.0f}%")
        print(f"   持仓: {r['qty']}股 × ¥{r['current']:.3f} = ¥{r['market_value']:,.2f}  "
              f"成本¥{r['cost']:.3f}  "
              f"盈亏 {'🟢' if r['pnl']>=0 else '🔴'}¥{r['pnl']:+,.2f} ({r['pnl_pct']:+.2f}%)")

        print(f"   技术面: MA10={r['ma10']:.2f} MA20={r['ma20']:.2f} MA60={r['ma60']:.2f}  "
              f"RSI={r['rsi']:.0f}  布林位置={r['boll_pos']*100:.0f}%  20日波动={r['vol20']:.1f}%")

        print(f"   关键位: 止损线 -8%@¥{r['stop_loss_8']:.2f} / -10%@¥{r['stop_loss_10']:.2f}  "
              f"止盈线 +15%@¥{r['take_profit_15']:.2f}")

        print(f"   策略投票:")
        for name, (sig, reason) in r["signals"].items():
            print(f"     {emoji(sig):2s} {name:6s}: {sig:<5s} — {reason}")
        print(f"   → 综合: BUY {r['vote_pct']['BUY']:.0f}% / "
              f"SELL {r['vote_pct']['SELL']:.0f}% / HOLD {r['vote_pct']['HOLD']:.0f}%")

    print("\n" + "=" * 80)
    print("🎯 操作建议汇总：")
    print("=" * 80)
    for r in results:
        if "error" in r: continue
        action = action_advice(r)
        print(f"  {emoji(r['decision'])} {r['name']}: {action}")
    print("=" * 80)
    print("\n⚠️  以上仅基于技术指标的机械分析，不构成投资建议。")
    print("    A 股有政策、消息、基本面影响，最终决策请结合自己判断。")


def action_advice(r):
    """转化成口语化建议"""
    pnl_pct = r["pnl_pct"]
    decision = r["decision"]

    if decision == "BUY":
        if pnl_pct < -5:
            return f"信号偏多但你已亏 {pnl_pct:.1f}%，**先观察 1-2 天**，回升再加仓更稳"
        return f"信号看涨，可考虑加仓，但仓位 {(r['market_value']/TOTAL_ASSETS*100):.0f}% 已不低，**轻仓加 100-200 股**即可"

    if decision == "SELL":
        if pnl_pct > 0:
            return f"💰 **建议止盈**，已赚 {pnl_pct:.1f}%，落袋为安"
        if pnl_pct < -8:
            return f"⚠️ **建议止损**，亏损 {pnl_pct:.1f}% 已破 -8%，**砍仓避免扩大**"
        return f"信号转弱但亏损 {pnl_pct:.1f}% 不深，**减半仓**先降风险，留观察底"

    # HOLD
    if pnl_pct < -8:
        return f"信号未明但你已亏 {pnl_pct:.1f}% 破止损线，**建议至少减半仓**"
    if pnl_pct < -5:
        return f"信号中性，亏 {pnl_pct:.1f}%，**继续观察，跌破 -8%（¥{r['stop_loss_8']:.2f}）必砍**"
    if pnl_pct > 10:
        return f"信号中性但已赚 {pnl_pct:.1f}%，**移动止盈到成本+5%（¥{r['cost']*1.05:.2f}）保利润**"
    return f"持有观望，关注 MA10(¥{r['ma10']:.2f}) 是否破"


def main():
    results = [analyze_position(s) for s in PORTFOLIO]
    print_report(results)

    # 存一份 JSON 给看板/记录
    out = os.path.join(PROJECT_DIR, "output", "portfolio_analysis.json")
    serializable = []
    for r in results:
        if "error" in r:
            serializable.append(r)
            continue
        rr = {k: v for k, v in r.items() if k != "signals"}
        rr["signals"] = {n: list(s) for n, s in r["signals"].items()}
        serializable.append(rr)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.now().isoformat(),
                   "total_assets": TOTAL_ASSETS, "cash": CASH,
                   "positions": serializable}, f, ensure_ascii=False, indent=2)
    print(f"\n📄 详情已存：{out}")


if __name__ == "__main__":
    main()
