"""scripts/swing_intraday_watch.py — 盘中波段机会盯盘（给你挂单提醒）

解决：波段日报只在 16:05，盘中好价砸到也听不见。

做什么（交易时段）：
  1. 扫稳定蓝筹池（同 swing_auto.STOCK_POOL）
  2. A/B 类且评分≥阈值 → 企微提醒「价格合适，可挂买入」
  3. 波段账户 #3 持仓触及止损/止盈 → 提醒卖
  4. 同股同日同类型只推一次（output/swing_intraday_state.json）

用法：
  python scripts/swing_intraday_watch.py
  python scripts/swing_intraday_watch.py --min-score 5 --no-push

建议 schtasks：交易日 09:35–14:50 每 10 分钟。
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

from swing_auto import STOCK_POOL, scan_stock  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("swing_intraday")

DB_PATH = ROOT / "data" / "sim_live_mirror.db"
OUT_DIR = ROOT / "output"
STATE_FILE = OUT_DIR / "swing_intraday_state.json"
LOG_DIR = OUT_DIR / "swing_intraday"
SWING_ACCOUNT_ID = 3
STOP_LOSS_PCT = 0.05
TAKE_PROFIT_PCT = 0.08
DEFAULT_MIN_SCORE = 5
EXECUTABLE = {"A", "B"}


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


def push_markdown(md: str) -> bool:
    import yaml
    url = None
    for name in ("config.local.yaml", "config.yaml"):
        p = ROOT / name
        if not p.exists():
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        url = (data.get("notify") or {}).get("wecom_webhook") or (data.get("notifier") or {}).get("wecom_webhook")
        if url and "YOUR_KEY" not in str(url):
            break
        url = None
    if not url:
        log.warning("无 webhook，跳过推送")
        return False
    body = json.dumps({"msgtype": "markdown", "markdown": {"content": md[:3500]}}, ensure_ascii=False).encode()
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
    for code, name in STOCK_POOL:
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
        hits.append({
            "kind": "BUY",
            "code": code6,
            "name": r["name"],
            "price": r["price"],
            "score": r["score"],
            "signal_type": r["signal_type"],
            "support": r["support"],
            "resist": r["resist"],
            "net_rr": r["net_rr"],
            "signals": "; ".join(s[0] for s in r.get("signals", [])[:2]),
            "stop": round(r["support"] * 0.98, 2),
            "target": r["resist"],
            "msg": (
                f"机会：限价 {r['support']:.2f}~{r['price']:.2f} 介入，"
                f"目标 {r['resist']:.2f}，止损 {r['support']*0.98:.2f}"
            ),
        })
        time.sleep(0.1)
    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits


def format_alert(a: dict, now: str) -> str:
    if a["kind"] == "BUY":
        return (
            f"## 盘中波段买入提醒 {now}\n"
            f"**{a['name']}({a['code']})** 现价 **{a['price']:.2f}**\n"
            f"- 类型 {a['signal_type']} | 分 {a['score']} | 净盈亏比 {a['net_rr']:.2f}\n"
            f"- 信号：{a.get('signals','')}\n"
            f"- **挂单建议**：{a['msg']}\n"
            f"> 模拟验证用提醒，请你自己在券商挂单"
        )
    tag = "止损" if a["kind"] == "SELL_STOP" else "止盈"
    return (
        f"## 盘中波段{tag}提醒 {now}\n"
        f"**{a['name']}({a['code']})** 现价 **{a['price']:.2f}**（{a['pnl_pct']:+.1f}%）\n"
        f"- {a['msg']}\n"
        f"- 参考止损 {a['stop']:.2f} / 目标 {a['target']:.2f}\n"
        f"> 请你自己确认后挂卖单"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=int, default=DEFAULT_MIN_SCORE)
    ap.add_argument("--force", action="store_true", help="非交易时段也跑（调试）")
    ap.add_argument("--no-push", action="store_true")
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
    for a in alerts:
        key = f"{a['kind']}:{a['code']}"
        if already_fired(state, key):
            log.info("已推过，跳过 %s", key)
            continue
        md = format_alert(a, now)
        log.info("%s %s %s", a["kind"], a["code"], a.get("msg"))
        (LOG_DIR / f"{date.today().isoformat()}.log").open("a", encoding="utf-8").write(
            f"{datetime.now().isoformat()} {key} {json.dumps(a, ensure_ascii=False)}\n"
        )
        if not args.no_push:
            if push_markdown(md):
                mark_fired(state, key)
                pushed += 1
                time.sleep(0.5)  # 企微频控
        else:
            print(md)
            print("---")
            mark_fired(state, key)
            pushed += 1

    save_state(state)
    log.info("本轮新提醒 %d / 候选 %d", pushed, len(alerts))
    print(f"新提醒 {pushed} 条（候选 {len(alerts)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
