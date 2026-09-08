"""scripts/swing_intraday_watch.py — 盘中波段机会盯盘（提醒 + 模拟成交）

解决：波段日报只在 16:05，盘中好价砸到也听不见。

做什么（交易时段）：
  1. 扫每日动态稳定池（output/swing_pool/latest.json，方法过滤+软上限约50）
  2. A/B 类且评分≥阈值 → 企微提醒「可挂买入」+ 账户 #3 同步模拟买入
  3. 模拟买卖成功 → 立刻另发一条 text+@all「请同步实盘」
  4. 波段账户 #3 持仓触及止损/止盈 → 提醒卖 + 同步模拟卖出
  5. 同股同日同类型只推/成交一次（output/swing_intraday_state.json）

用法：
  python scripts/swing_intraday_watch.py
  python scripts/swing_intraday_watch.py --min-score 5 --no-push
  python scripts/swing_intraday_watch.py --no-trade   # 只提醒不模拟

建议 schtasks：交易日 09:35–14:50 每 10 分钟（由 QuantPulse 调用）。
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
import urllib.request
from datetime import date, datetime, time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from swing_auto import get_stock_pool, scan_stock  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("swing_intraday")

from quant_core.swing_params import load_swing_params  # noqa: E402
from sim.config_resolver import resolve_artifact_root, resolve_db_path  # noqa: E402

DB_PATH = resolve_db_path()
OUT_DIR = resolve_artifact_root()
STATE_FILE = OUT_DIR / "swing_intraday_state.json"
LOG_DIR = OUT_DIR / "swing_intraday"
SWING_ACCOUNT_ID = 3
# 执行参数真源：quant_core/swing_params.py。盘中与收盘必须用同一套值，
# 否则会出现「盘中喊买、收盘按另一套阈值不认」的错位。
PARAMS = load_swing_params()
STOP_LOSS_PCT = PARAMS.stop_loss_pct
TAKE_PROFIT_PCT = PARAMS.take_profit_pct
DEFAULT_MIN_SCORE = PARAMS.min_score_buy
EXECUTABLE = set(PARAMS.executable_types)


def is_trading_now() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.time()
    am = dtime(9, 30) <= t <= dtime(11, 30)
    pm = dtime(13, 0) <= t <= dtime(14, 57)
    return am or pm


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"date": date.today().isoformat(), "fired": []}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"date": date.today().isoformat(), "fired": []}
    if data.get("date") != date.today().isoformat():
        return {"date": date.today().isoformat(), "fired": []}
    return data


def save_state(state: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def already_fired(state: dict, key: str) -> bool:
    return key in state.get("fired", [])


def mark_fired(state: dict, key: str) -> None:
    state.setdefault("fired", []).append(key)


def _webhook_url() -> str | None:
    import yaml
    for name in ("config.local.yaml", "config.yaml"):
        p = ROOT / name
        if not p.exists():
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        url = (data.get("notify") or {}).get("wecom_webhook") or (data.get("notifier") or {}).get("wecom_webhook")
        if url and "YOUR_KEY" not in str(url):
            return str(url)
    return None


def _post_wecom(payload: dict) -> bool:
    url = _webhook_url()
    if not url:
        log.warning("无 webhook，跳过推送")
        return False
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read().decode())
            ok = r.get("errcode") == 0
            log.info("企微: %s", r)
            return ok
    except Exception as e:
        log.error("推送失败: %s", e)
        return False


def push_markdown(md: str) -> bool:
    return _post_wecom({"msgtype": "markdown", "markdown": {"content": md[:3500]}})


def push_text(content: str, mentioned_list: list[str] | None = None) -> bool:
    text: dict = {"content": content[:2000]}
    if mentioned_list:
        text["mentioned_list"] = mentioned_list
    return _post_wecom({"msgtype": "text", "text": text})


def format_sync_trade_text(fill: dict) -> str | None:
    """模拟成交立刻同步实盘的明文（给人手机震一下）。"""
    if not fill or not fill.get("ok"):
        return None
    side = fill.get("side")
    name = fill.get("name") or fill.get("code")
    code = fill.get("code")
    qty = fill.get("qty")
    price = float(fill.get("price") or 0)
    reason = fill.get("reason") or ""
    if side == "BUY":
        return (
            f"🚨【立刻同步实盘】波段模拟已买入\n"
            f"{name}({code}) {qty}股 @ {price:.2f}\n"
            f"止损 {fill.get('stop')} / 目标 {fill.get('target')}\n"
            f"原因：{reason}\n"
            f"请马上在券商挂同样买单"
        )
    if side == "SELL":
        realized = float(fill.get("realized") or 0)
        return (
            f"🚨【立刻同步实盘】波段模拟已卖出\n"
            f"{name}({code}) {qty}股 @ {price:.2f}\n"
            f"已实现约 ¥{realized:+.0f}\n"
            f"原因：{reason}\n"
            f"请马上在券商确认后挂卖单"
        )
    return None


def push_sync_trade(fill: dict) -> bool:
    """模拟成交成功 → text + @all，催人同步实盘。"""
    text = format_sync_trade_text(fill)
    if not text:
        return False
    ok = push_text(text, mentioned_list=["@all"])
    if ok:
        log.info("同步实盘提醒已推 %s %s", fill.get("side"), fill.get("code"))
    return ok


def get_quote_6(code6: str) -> dict | None:
    prefix = "sh" if code6.startswith(("5", "6", "9")) else "sz"
    try:
        req = urllib.request.Request(
            f"https://qt.gtimg.cn/q={prefix}{code6}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        vals = urllib.request.urlopen(req, timeout=8).read().decode("gbk").split('"')[1].split("~")
        return {"name": vals[1], "price": float(vals[3] or 0), "change_pct": float(vals[32] or 0)}
    except Exception:
        return None


def load_swing_positions() -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM sim_positions WHERE account_id=? AND quantity>0",
            (SWING_ACCOUNT_ID,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def check_positions() -> list[dict]:
    alerts = []
    for p in load_swing_positions():
        code = str(p["stock_code"]).zfill(6)[-6:]
        q = get_quote_6(code)
        if not q or q["price"] <= 0:
            continue
        price = q["price"]
        cost = float(p.get("avg_cost") or 0)
        if cost <= 0:
            continue
        stop = cost * (1 - STOP_LOSS_PCT)
        target = cost * (1 + TAKE_PROFIT_PCT)
        pnl_pct = (price / cost - 1) * 100
        name = p.get("stock_name") or q["name"]
        if price <= stop:
            alerts.append({
                "kind": "SELL_STOP",
                "code": code,
                "name": name,
                "price": price,
                "pnl_pct": pnl_pct,
                "stop": stop,
                "target": target,
                "msg": f"止损线破位：建议卖出挂单 ~{price:.2f}",
            })
        elif price >= target:
            alerts.append({
                "kind": "SELL_TP",
                "code": code,
                "name": name,
                "price": price,
                "pnl_pct": pnl_pct,
                "stop": stop,
                "target": target,
                "msg": f"止盈触发：可挂卖 ~{price:.2f}",
            })
        time.sleep(0.08)
    return alerts


def scan_opportunities(min_score: int) -> list[dict]:
    hits = []
    for code, name in get_stock_pool():
        try:
            r = scan_stock(code, name)
        except Exception:
            r = None
        if not r:
            time.sleep(0.1)
            continue
        if r.get("signal_type") not in EXECUTABLE:
            time.sleep(0.1)
            continue
        if int(r.get("score") or 0) < min_score:
            time.sleep(0.1)
            continue
        code6 = str(r["code"])[-6:]
        support = float(r.get("support") or 0)
        resist = float(r.get("resist") or 0)
        price = float(r["price"])
        stop = round(support * 0.98, 2) if support else round(price * 0.95, 2)
        target = resist if resist else round(price * 1.08, 2)
        hits.append({
            "kind": "BUY",
            "code": code6,
            "name": r["name"],
            "price": price,
            "score": r["score"],
            "signal_type": r["signal_type"],
            "support": support,
            "resist": resist,
            "support_name": r.get("support_name") or "",
            "resist_name": r.get("resist_name") or "",
            "net_rr": r["net_rr"],
            "risk_reward": r.get("risk_reward"),
            "upside_pct": r.get("upside_pct"),
            "downside_pct": r.get("downside_pct"),
            "fee_ratio": r.get("fee_ratio"),
            "suggested_shares": r.get("suggested_shares"),
            "suggested_amount": r.get("suggested_amount"),
            "signals": "; ".join(s[0] for s in r.get("signals", [])[:2]),
            "stop": stop,
            "target": target,
            "msg": (
                f"机会：限价 {support:.2f}~{price:.2f} 介入，"
                f"目标 {resist:.2f}，止损 {support*0.98:.2f}"
                if support and resist
                else f"现价附近介入 ~{price:.2f}"
            ),
        })
        time.sleep(0.1)
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits


def _fmt_pnl_block(a: dict) -> str:
    """买入提醒：把扫描里算过的盈亏字段全写上。"""
    lines = [
        f"- 类型 {a['signal_type']} | 分 {a['score']} | 净盈亏比 {a['net_rr']:.2f}"
    ]
    up = a.get("upside_pct")
    down = a.get("downside_pct")
    rr = a.get("risk_reward")
    fee = a.get("fee_ratio")
    bits = []
    if up is not None and down is not None:
        bits.append(f"预期涨 {float(up):+.2f}% / 跌 {float(down):.2f}%")
    if rr is not None:
        bits.append(f"毛盈亏比 {float(rr):.2f}")
    if fee is not None:
        bits.append(f"手续费约 {float(fee):.3f}%")
    if bits:
        lines.append(f"- 盈亏：{' | '.join(bits)}")
    sn = a.get("support_name") or ""
    rn = a.get("resist_name") or ""
    if a.get("support") and a.get("resist"):
        s_lab = f"{sn}{a['support']:.2f}" if sn else f"{a['support']:.2f}"
        r_lab = f"{rn}{a['resist']:.2f}" if rn else f"{a['resist']:.2f}"
        lines.append(f"- 技术位：支撑 {s_lab} → 阻力 {r_lab}")
    amt = a.get("suggested_amount")
    shares = a.get("suggested_shares")
    if amt is not None and shares is not None:
        lines.append(f"- 建议仓位：约 {float(amt):.0f} 元（{int(shares)} 股）")
    return "\n".join(lines)


def _fmt_sim_footer(a: dict) -> str:
    fill = a.get("sim_fill")
    if not fill:
        return "> 模拟验证用提醒，请你自己在券商挂单"
    if fill.get("ok") and fill.get("side") == "BUY":
        return (
            f"- **模拟已买**：账户#3 {fill.get('qty')}股 @ {fill.get('price'):.2f}，"
            f"止损 {fill.get('stop')} / 目标 {fill.get('target')}\n"
            f"> 🚨 已另发@所有人同步提醒；请立刻在券商挂同样买单"
        )
    if fill.get("ok") and fill.get("side") == "SELL":
        return (
            f"- **模拟已卖**：账户#3 {fill.get('qty')}股 @ {fill.get('price'):.2f}，"
            f"已实现约 ¥{float(fill.get('realized') or 0):+.0f}\n"
            f"> 🚨 已另发@所有人同步提醒；请立刻在券商确认后挂卖单"
        )
    return f"- 模拟未成交：{fill.get('reason') or '未知'}\n> 仍可作挂单参考，请你自己在券商操作"


def format_alert(a: dict, now: str) -> str:
    fill = a.get("sim_fill") or {}
    synced = fill.get("ok")
    if a["kind"] == "BUY":
        title = (
            f"## 🚨【立刻同步实盘】波段模拟已买入 {now}"
            if synced
            else f"## 盘中波段买入提醒 {now}"
        )
        return (
            f"{title}\n"
            f"**{a['name']}({a['code']})** 现价 **{a['price']:.2f}**\n"
            f"{_fmt_pnl_block(a)}\n"
            f"- 信号：{a.get('signals','')}\n"
            f"- **挂单建议**：{a['msg']}\n"
            f"{_fmt_sim_footer(a)}"
        )
    tag = "止损" if a["kind"] == "SELL_STOP" else "止盈"
    title = (
        f"## 🚨【立刻同步实盘】波段模拟已卖出({tag}) {now}"
        if synced
        else f"## 盘中波段{tag}提醒 {now}"
    )
    return (
        f"{title}\n"
        f"**{a['name']}({a['code']})** 现价 **{a['price']:.2f}**（{a['pnl_pct']:+.1f}%）\n"
        f"- {a['msg']}\n"
        f"- 参考止损 {a['stop']:.2f} / 目标 {a['target']:.2f}\n"
        f"{_fmt_sim_footer(a)}"
    )


def try_sim_fill(a: dict) -> dict:
    """提醒同时写账户 #3：买→sim_buy，卖→sim_sell。"""
    from swing_daily_report import (  # noqa: WPS433
        MAX_POSITIONS,
        allow_same_day_replace,
        ensure_swing_account,
        load_positions,
        sim_buy,
        sim_sell,
        sync_swing_fixed_stops,
        today_sold_codes,
    )

    ensure_swing_account()
    try:
        sync_swing_fixed_stops()
    except Exception as e:
        log.warning("钉回固定止损失败: %s", e)
    code = str(a["code"]).zfill(6)[-6:]
    if a["kind"] == "BUY":
        if not allow_same_day_replace() and today_sold_codes(date.today().isoformat()):
            return {"ok": False, "code": code, "reason": "同日已有卖出，冷却至下一交易日再开仓"}
        held = load_positions()
        held_codes = {str(p["stock_code"]).zfill(6)[-6:] for p in held}
        if code in held_codes:
            return {"ok": False, "code": code, "reason": "已持有，跳过重复买"}
        if len(held) >= MAX_POSITIONS:
            return {"ok": False, "code": code, "reason": f"仓位已满({MAX_POSITIONS})"}
        reason = (
            f"盘中提醒|{a.get('signal_type','?')}分{a.get('score','?')} "
            f"rr={float(a.get('net_rr') or 0):.2f}"
        )
        return sim_buy(code, a.get("name") or code, float(a["price"]), reason)

    if a["kind"] in ("SELL_STOP", "SELL_TP"):
        held = load_positions()
        pos = next((p for p in held if str(p["stock_code"]).zfill(6)[-6:] == code), None)
        if not pos:
            return {"ok": False, "code": code, "reason": "无持仓可卖"}
        tag = "盘中止损" if a["kind"] == "SELL_STOP" else "盘中止盈"
        return sim_sell(pos, float(a["price"]), tag)

    return {"ok": False, "code": code, "reason": f"未知类型 {a.get('kind')}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    ap.add_argument("--force", action="store_true", help="非交易时段也跑（调试）")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-trade", action="store_true", help="只提醒，不写模拟成交")
    ap.add_argument("--max-buy-alerts", type=int, default=3, help="单次最多推几只买入")
    args = ap.parse_args()

    if not args.force and not is_trading_now():
        log.info("非交易时段，退出")
        print("非交易时段")
        return 0

    now = datetime.now().strftime("%H:%M")
    state = load_state()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    alerts: list[dict] = []
    alerts.extend(check_positions())
    buys = scan_opportunities(args.min_score)[: args.max_buy_alerts]
    alerts.extend(buys)

    pushed = 0
    traded = 0
    sync_pushed = 0
    for a in alerts:
        key = f"{a['kind']}:{a['code']}"
        if already_fired(state, key):
            log.info("已处理，跳过 %s", key)
            continue

        # 先模拟再推：避免只提醒不成交；同 key 只成交一次
        if not args.no_trade:
            fill = try_sim_fill(a)
            a["sim_fill"] = fill
            if fill.get("ok"):
                traded += 1
            log.info("模拟 %s %s -> %s", a["kind"], a["code"], fill)
        else:
            a["sim_fill"] = None

        md = format_alert(a, now)
        log.info("%s %s %s", a["kind"], a["code"], a.get("msg"))
        log_payload = {k: v for k, v in a.items() if k != "sim_fill"}
        log_payload["sim_fill"] = a.get("sim_fill")
        (LOG_DIR / f"{date.today().isoformat()}.log").open("a", encoding="utf-8").write(
            f"{datetime.now().isoformat()} {key} {json.dumps(log_payload, ensure_ascii=False)}\n"
        )

        # 无论推送成败都 mark：防止 Pulse 重试导致重复买入
        mark_fired(state, key)
        if not args.no_push:
            if push_markdown(md):
                pushed += 1
                time.sleep(0.3)
            # 成交成功再砸一条 @all 明文，手机必震
            if a.get("sim_fill") and a["sim_fill"].get("ok"):
                if push_sync_trade(a["sim_fill"]):
                    sync_pushed += 1
                    time.sleep(0.3)
        else:
            print(md)
            sync_txt = format_sync_trade_text(a.get("sim_fill") or {})
            if sync_txt:
                print(sync_txt)
            print("---")
            pushed += 1

    save_state(state)
    log.info(
        "本轮新提醒 %d / 模拟成交 %d / 同步@all %d / 候选 %d",
        pushed, traded, sync_pushed, len(alerts),
    )
    print(f"新提醒 {pushed} 条（模拟成交 {traded}，同步@all {sync_pushed}，候选 {len(alerts)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
