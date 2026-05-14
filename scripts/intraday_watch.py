#!/usr/bin/env python3
"""
scripts/intraday_watch.py — 盘中实时监控

四个调用模式：
  python scripts/intraday_watch.py auction    # 集合竞价快报（9:24/9:31 跑）
  python scripts/intraday_watch.py monitor    # 一次性持仓 + 价格快照
  python scripts/intraday_watch.py check      # 触发预警检查（每 5 分钟跑）
  python scripts/intraday_watch.py post       # 收盘复盘（15:05 跑）

输出：
  - 控制台打印
  - 写入 output/intraday_log.jsonl
  - 返回 stdout 文本（cron 把这个 push 给用户）
"""

import os
import sys
import json
from datetime import datetime, time as dtime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.realtime_price import get_latest_prices

PROJECT_DIR = Path(__file__).resolve().parents[1]
LOG_FILE = PROJECT_DIR / "output" / "intraday_log.jsonl"
ALERT_STATE = PROJECT_DIR / "output" / "alert_state.json"

# 你的持仓（来自 5/14 02:17 截图）
PORTFOLIO = [
    {"code": "002256", "name": "兆新股份", "qty": 700, "cost": 5.246},
    {"code": "000967", "name": "盈峰环境", "qty": 400, "cost": 12.660},
    {"code": "002453", "name": "华软科技", "qty": 300, "cost": 6.467},
    {"code": "600330", "name": "天通股份", "qty": 300, "cost": 33.774},
]

# 关键阈值（最重要的报警线）
ALERTS = [
    {"code": "002256", "name": "兆新股份", "level": "loss",   "trigger": 4.83,  "msg": "止损 -8% 触发！建议全部卖出"},
    {"code": "002256", "name": "兆新股份", "level": "loss2",  "trigger": 4.72,  "msg": "深度亏损 -10%！必须砍仓"},
    {"code": "000967", "name": "盈峰环境", "level": "profit", "trigger": 13.29, "msg": "止盈 +5% 跌破，建议落袋"},
    {"code": "000967", "name": "盈峰环境", "level": "loss",   "trigger": 11.65, "msg": "罕见止损线触发"},
    {"code": "002453", "name": "华软科技", "level": "loss",   "trigger": 5.95,  "msg": "止损 -8% 触发"},
    {"code": "002453", "name": "华软科技", "level": "ma10",   "trigger": 6.03,  "msg": "跌破 MA10，建议减仓观察"},
    {"code": "600330", "name": "天通股份", "level": "loss",   "trigger": 31.07, "msg": "止损 -8% 触发"},
    {"code": "600330", "name": "天通股份", "level": "ma10",   "trigger": 29.67, "msg": "跌破 MA10，建议减仓"},
]

CODES = [p["code"] for p in PORTFOLIO]


# ========== 工具 ==========
def _now():
    return datetime.now()


def _is_trading_time():
    n = _now()
    if n.weekday() >= 5:
        return False
    t = n.time()
    return (dtime(9, 15) <= t <= dtime(11, 30)) or (dtime(13, 0) <= t <= dtime(15, 0))


def _log(payload):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload["timestamp"] = _now().isoformat()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_alert_state():
    if ALERT_STATE.exists():
        return json.loads(ALERT_STATE.read_text(encoding="utf-8"))
    return {}


def _save_alert_state(state):
    ALERT_STATE.parent.mkdir(parents=True, exist_ok=True)
    ALERT_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _emoji(pct):
    return "🟢" if pct >= 0 else "🔴" if pct < 0 else "⚪"


# ========== 模式 1：集合竞价快报 ==========
def cmd_auction():
    """9:24 调用 → 抓集合竞价价格 / 9:31 调用 → 抓真实开盘"""
    n = _now()
    is_premarket = n.time() < dtime(9, 25)
    is_postopen  = n.time() < dtime(9, 35)

    label = "集合竞价（9:25 撮合前）" if is_premarket else "开盘 1 分钟"

    prices = get_latest_prices(CODES)
    if not prices:
        return "❌ 行情拉取失败"

    lines = [f"🌅 **{label}** {n.strftime('%Y-%m-%d %H:%M')}\n"]
    big_moves = []

    for p in PORTFOLIO:
        code = p["code"]
        if code not in prices:
            lines.append(f"❓ {p['name']}({code}): 无数据")
            continue
        d = prices[code]
        last = d["price"]
        yest = d.get("yesterday_close", 0) or last
        op = d.get("open", 0) or last

        change = (last - yest) / yest * 100 if yest else 0
        cost_pnl = (last - p["cost"]) / p["cost"] * 100

        emoji = "📈" if change > 1 else "📉" if change < -1 else "➡️"
        lines.append(
            f"{emoji} **{p['name']}**({code})  ¥{last:.2f}  "
            f"vs昨收{change:+.2f}%  vs成本{cost_pnl:+.2f}%"
        )
        lines.append(f"   开盘¥{op:.2f} 最高¥{d['high']:.2f} 最低¥{d['low']:.2f}")

        # 异动
        if abs(change) >= 3:
            big_moves.append(f"{p['name']} {change:+.2f}%")

    if big_moves:
        lines.append("\n⚠️ **大幅异动**：" + "、".join(big_moves))

    # 关键阈值预检
    triggered = []
    for a in ALERTS:
        if a["code"] not in prices:
            continue
        last = prices[a["code"]]["price"]
        if a["level"].startswith("loss") and last <= a["trigger"]:
            triggered.append(f"🚨 {a['name']} ¥{last:.2f} ≤ {a['trigger']} → {a['msg']}")
        elif a["level"] == "profit" and last <= a["trigger"]:
            triggered.append(f"💰 {a['name']} ¥{last:.2f} ≤ {a['trigger']} → {a['msg']}")
        elif a["level"] == "ma10" and last <= a["trigger"]:
            triggered.append(f"⚠️ {a['name']} ¥{last:.2f} ≤ MA10 {a['trigger']} → {a['msg']}")

    if triggered:
        lines.append("\n## 🚨 触发警报")
        lines.extend(triggered)
    else:
        lines.append("\n✅ 暂无触发关键阈值")

    out = "\n".join(lines)
    print(out)
    _log({"mode": "auction", "is_premarket": is_premarket, "prices": prices})
    return out


# ========== 模式 2：完整持仓快照 ==========
def cmd_monitor():
    n = _now()
    prices = get_latest_prices(CODES)

    total_market = 0
    total_pnl = 0
    lines = [f"📊 **持仓监控** {n.strftime('%Y-%m-%d %H:%M:%S')}\n"]
    for p in PORTFOLIO:
        if p["code"] not in prices:
            lines.append(f"❓ {p['name']}({p['code']}): 无数据")
            continue
        last = prices[p["code"]]["price"]
        mv = last * p["qty"]
        pnl = (last - p["cost"]) * p["qty"]
        pnl_pct = (last - p["cost"]) / p["cost"] * 100
        total_market += mv
        total_pnl += pnl

        lines.append(
            f"{_emoji(pnl_pct)} {p['name']}({p['code']}) "
            f"¥{last:.2f} × {p['qty']} = ¥{mv:,.0f}  "
            f"盈亏 ¥{pnl:+,.0f} ({pnl_pct:+.2f}%)"
        )

    lines.append(f"\n💼 总市值 ¥{total_market:,.2f}  盈亏 ¥{total_pnl:+,.2f}")
    out = "\n".join(lines)
    print(out)
    _log({"mode": "monitor", "total_market": total_market, "total_pnl": total_pnl})
    return out


# ========== 模式 3：触发预警（每 5 分钟跑一次） ==========
def cmd_check():
    """关键：触发了才返回非空，否则返回空字符串（cron 看到空就不发消息）"""
    if not _is_trading_time():
        # 非交易时间不跑
        return ""

    state = _load_alert_state()
    today = _now().strftime("%Y-%m-%d")
    if state.get("date") != today:
        state = {"date": today, "fired": []}

    prices = get_latest_prices(CODES)
    if not prices:
        return ""

    new_alerts = []
    for a in ALERTS:
        key = f"{today}:{a['code']}:{a['level']}"
        if key in state["fired"]:
            continue  # 同一天同一级别只报一次
        if a["code"] not in prices:
            continue
        last = prices[a["code"]]["price"]
        if last <= 0:
            continue
        if last <= a["trigger"]:
            new_alerts.append({
                "name": a["name"], "code": a["code"], "level": a["level"],
                "trigger": a["trigger"], "current": last, "msg": a["msg"],
            })
            state["fired"].append(key)

    if not new_alerts:
        return ""  # 啥事没有，cron 别推消息

    _save_alert_state(state)

    n = _now()
    lines = [f"🚨 **触发预警** {n.strftime('%H:%M:%S')}\n"]
    for a in new_alerts:
        emoji = "💰" if a["level"] == "profit" else "🚨"
        lines.append(f"{emoji} **{a['name']}**({a['code']})  现价 ¥{a['current']:.3f}  "
                     f"触发线 ¥{a['trigger']}")
        lines.append(f"   → {a['msg']}")
    lines.append("\n⚠️ 立刻去东财 App 看一眼，决定是否执行操作")
    out = "\n".join(lines)
    print(out)
    _log({"mode": "check", "alerts": new_alerts})
    return out


# ========== 模式 4：收盘复盘 ==========
def cmd_post():
    n = _now()
    prices = get_latest_prices(CODES)

    total_pnl_today = 0
    total_pnl_overall = 0
    lines = [f"🌆 **收盘复盘** {n.strftime('%Y-%m-%d %H:%M')}\n"]

    for p in PORTFOLIO:
        if p["code"] not in prices:
            lines.append(f"❓ {p['name']}({p['code']}): 无数据")
            continue
        d = prices[p["code"]]
        last = d["price"]
        yest = d.get("yesterday_close", 0) or last
        today_pnl = (last - yest) * p["qty"]
        overall_pnl = (last - p["cost"]) * p["qty"]
        total_pnl_today += today_pnl
        total_pnl_overall += overall_pnl

        lines.append(
            f"{_emoji(today_pnl)} {p['name']} 今日{(last-yest)/yest*100:+.2f}% 盈亏¥{today_pnl:+.0f}  |  "
            f"累计{(last-p['cost'])/p['cost']*100:+.2f}% ¥{overall_pnl:+.0f}"
        )

    lines.append(f"\n📊 今日盈亏 ¥{total_pnl_today:+,.2f}  |  累计 ¥{total_pnl_overall:+,.2f}")
    lines.append(f"\n👉 用 `python scripts/portfolio_analyze.py` 看明日策略建议")

    out = "\n".join(lines)
    print(out)
    _log({"mode": "post", "today_pnl": total_pnl_today, "overall_pnl": total_pnl_overall})
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "monitor"
    fn_map = {
        "auction": cmd_auction,
        "monitor": cmd_monitor,
        "check":   cmd_check,
        "post":    cmd_post,
    }
    if cmd not in fn_map:
        print(f"未知模式: {cmd}，可选: {list(fn_map.keys())}")
        sys.exit(1)
    fn_map[cmd]()


if __name__ == "__main__":
    main()
